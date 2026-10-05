"""Narration, audio timing and subtitle phases shared by video pipeline."""

from __future__ import annotations

import os
import json
import sys
import time
from dataclasses import dataclass
from math import isfinite

from . import ffmpeg as ff
from .audio.artifacts import (TTSCacheManifest, legacy_words_match_text,
                              read_tts_manifest, tts_input_signature,
                              words_signature, write_tts_manifest)
from .stages import subs as subs_stage
from .stages import tts as tts_stage
from .stages.scene_contract import SemanticScene, TimelineSpan
from .stages.scene_projection import Chapter
from .stages.timing import align_word_boundaries, proportional_spans


@dataclass(frozen=True)
class AudioStageResult:
    timeline_spans: tuple[TimelineSpan, ...]
    words: list[dict] | None
    audio_duration: float
    tts_info: dict
    timed_source: str
    cue_count: int
    subtitles_changed: bool
    warnings: tuple[str, ...]
    stage_times: dict[str, float]

    def __post_init__(self) -> None:
        if any(not isinstance(span, TimelineSpan) for span in self.timeline_spans):
            raise TypeError("audio result timing must contain TimelineSpan values")
        if isinstance(self.audio_duration, bool) or not isinstance(
                self.audio_duration, (int, float)) or not isfinite(
                    self.audio_duration) or self.audio_duration < 0:
            raise ValueError("audio result duration must be finite and non-negative")
        if self.timed_source not in {"wordboundary", "proporcional"}:
            raise ValueError("audio result timing source is invalid")
        if isinstance(self.cue_count, bool) or not isinstance(self.cue_count, int) \
                or self.cue_count < 0:
            raise ValueError("audio subtitle cue count must be non-negative")
        if not isinstance(self.subtitles_changed, bool):
            raise TypeError("audio subtitle change marker must be boolean")
        if any(not isinstance(value, str) or not value.strip()
               for value in self.warnings):
            raise ValueError("audio warnings must be non-empty strings")
        if not isinstance(self.stage_times, dict) or any(
                not isinstance(key, str) or isinstance(value, bool)
                or not isinstance(value, (int, float)) or not isfinite(value)
                or value < 0 for key, value in self.stage_times.items()):
            raise ValueError("audio stage times must be finite non-negative values")


def run_audio_stages(script_text: str, semantic_scenes: tuple[SemanticScene, ...],
                     timeline_spans: tuple[TimelineSpan, ...], paths, cfg, force: bool,
                     metrics, emit, write_json,
                     pacing=None, caption_style=None) -> AudioStageResult:
    """Run TTS, timing alignment and subtitle generation."""
    start_time = time.monotonic()
    warnings: list[str] = []
    stage_times: dict[str, float] = {}
    emit(4, "Gerando narração")
    words = None
    tts_cached = False
    tts_signature = tts_input_signature(
        script_text, cfg.tts_provider, cfg.tts_voice, cfg.tts_speed,
        cfg.duration_target, cfg.language)
    manifest = read_tts_manifest(paths.tts_manifest_json)
    if not force and os.path.isfile(paths.narration_wav):
        words = _read_words(paths.words_json)
        partial_cache = (words is not None
                         and not tts_stage.tts_coverage_ok(words, script_text))
        if partial_cache:
            print(f"AVISO: narração em cache cobre só "
                  f"{len(words or [])}/{len(script_text.split())} palavras — "
                  "sintetizando de novo.", file=sys.stderr)
            warnings.append("narração parcial em cache — refeita")
        cached = (None if partial_cache else _cache_result(
            manifest, words, tts_signature, script_text, paths, cfg))
        if cached is not None:
            tts_info, has_boundaries = cached
            if has_boundaries and (words is None or
                                   not tts_stage.tts_coverage_ok(words, script_text)):
                cached = None
            elif os.path.isfile(paths.words_json):
                if not has_boundaries:
                    cached = None
                    words = None
                    warnings.append("palavras antigas sem identidade válida — refeitas")
            if cached is not None:
                audio_duration = ff.probe_duration(paths.narration_wav)
                tts_info["reused"] = True
                tts_cached = True
                if manifest is None:
                    _write_manifest(paths.tts_manifest_json, tts_signature,
                                    tts_info, audio_duration, words)
        if cached is None:
            words = None
            if manifest is not None or os.path.isfile(paths.narration_wav):
                if "narração parcial em cache — refeita" not in warnings:
                    warnings.append("cache de TTS obsoleto — narração refeita")
                try:
                    os.unlink(paths.tts_manifest_json)
                except FileNotFoundError:
                    pass
    if not tts_cached:
        try:
            os.unlink(paths.tts_manifest_json)
        except FileNotFoundError:
            pass
        try:
            os.unlink(paths.words_json)
        except FileNotFoundError:
            pass
        result = tts_stage.synthesize(
            script_text, paths.narration_wav, cfg.tts_provider, cfg.tts_voice,
            cfg.tts_speed, cfg.duration_target, words_path=paths.words_json,
            metrics=metrics, language=cfg.language)
        if not isinstance(result, tts_stage.TTSResult):
            raise TypeError("synthesize must return TTSResult")
        audio_duration = result.duration
        words = result.words
        if words is not None:
            _write_words(paths.words_json, words)
        else:
            try:
                os.unlink(paths.words_json)
            except FileNotFoundError:
                pass
        tts_info = {"provider": result.provider, "voice": result.voice,
                    "speed": result.speed, "reused": False}
        _write_manifest(paths.tts_manifest_json, tts_signature, tts_info,
                        audio_duration, words)
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
                            tuple(warnings), stage_times)


def _read_words(path):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, list) else None
    except (OSError, ValueError):
        return None


def _write_words(path, words):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(words, stream, ensure_ascii=False, indent=1)


def _cache_result(manifest, words, signature, script_text, paths, cfg):
    if manifest is not None:
        if manifest.input_signature != signature:
            return None
        if manifest.has_word_boundaries:
            if words is None or words_signature(words) != manifest.words_signature:
                return None
        return ({"provider": manifest.provider, "voice": manifest.voice,
                 "speed": manifest.speed}, manifest.has_word_boundaries)

    # Old projects have no TTS manifest. Reuse only when saved metadata and
    # word-boundary text prove the audio belongs to this exact narration.
    if not os.path.isfile(paths.metadata_json) or words is None:
        return None
    try:
        with open(paths.metadata_json, encoding="utf-8") as stream:
            previous = json.load(stream)
    except (OSError, ValueError):
        return None
    if (not isinstance(previous, dict)
            or previous.get("script_chars") != len(script_text)
            or previous.get("duration_target") != cfg.duration_target
            or not legacy_words_match_text(words, script_text)
            or not _legacy_voice_matches(previous.get("tts_voice"), cfg)):
        return None
    provider = previous.get("tts_provider")
    if provider not in ("edge-tts", "espeak-ng"):
        return None
    saved_speed = previous.get("tts_speed")
    if isinstance(saved_speed, bool) or not isinstance(saved_speed, int):
        return None
    if cfg.tts_provider != provider:
        return None
    if provider == "espeak-ng" and saved_speed != cfg.tts_speed:
        return None
    return ({"provider": provider, "voice": previous.get("tts_voice"),
             "speed": saved_speed}, True)


def _legacy_voice_matches(previous_voice, cfg):
    if not isinstance(previous_voice, str) or not previous_voice:
        return False
    requested = str(cfg.tts_voice or "")
    generic = requested.casefold() in ("", "pt-br", "en-us")
    if not generic:
        return previous_voice.casefold() == requested.casefold()
    expected_language = "en" if str(cfg.language).lower().startswith("en") else "pt"
    voice_language = previous_voice.casefold().split("-", 1)[0]
    return voice_language == expected_language


def _write_manifest(path, signature, tts_info, duration, words):
    manifest = TTSCacheManifest(
        input_signature=signature, provider=str(tts_info["provider"]),
        voice=str(tts_info["voice"]), speed=int(tts_info["speed"]),
        duration=float(duration), has_word_boundaries=words is not None,
        words_signature=words_signature(words))
    write_tts_manifest(path, manifest)
