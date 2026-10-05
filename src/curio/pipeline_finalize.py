"""Human narration finalization workflow for an existing Curio project."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time

from . import ffmpeg as ff
from . import pipeline_metadata as pipeline_metadata_stage
from . import pipeline_render as pipeline_render_stage
from . import project_artifacts
from .audio import composition as audio_composition
from .audio import selection as audio_selection
from .audio.library import audio_seed
from .config import CurioConfig
from .metrics import RunMetrics
from .project_paths import VideoPaths
from .media.selection_metrics import MediaMetricsInput
from .runlog import current_log_path, event as run_event, set_stage as set_log_stage
from .stages import editorial as editorial_stage
from .stages import render as render_stage
from .stages import subs as subs_stage
from .stages import transcribe as transcribe_stage
from .stages import visual_timeline as visual_timeline_stage
from .stages.scenes import Chapter
from .stages.scene_contract import TimelineSpan
from .stages.visual_beats import BEAT_SECONDS


def _probe_streams(path: str) -> list[dict]:
    import json as _json
    proc = ff.run([ff.FFPROBE, "-v", "error", "-show_entries",
                   "stream=codec_type,duration", "-of", "json", path])
    if proc.returncode != 0:
        raise ff.FFMpegError(f"ffprobe falhou em {path}: {proc.stderr.strip()}")
    return (_json.loads(proc.stdout).get("streams") or [])


def run_finalize(slug: str, audio_src: str, cfg: CurioConfig,
                 paths: VideoPaths, force: bool = False, on_progress=None) -> dict:
    """Une áudio humano ao vídeo silencioso: transcreve, legenda, merge."""
    started = time.monotonic()
    metrics = RunMetrics(slug, audio_src, "human-finalize")
    for need in (paths.chapters_json, paths.timeline_json, paths.media_json,
                 paths.silent_mp4):
        if not os.path.isfile(need):
            raise FileNotFoundError(
                f"projeto '{slug}' incompleto ({need} ausente). "
                "Rode `generate --narration human` primeiro.")
    if not os.path.isfile(audio_src):
        raise FileNotFoundError(f"áudio não encontrado: {audio_src}")
    if not any(s.get("codec_type") == "audio" for s in _probe_streams(audio_src)):
        raise ValueError(f"arquivo sem trilha de áudio: {audio_src}")

    saved_timeline = [Chapter.from_dict(row)
                      for row in project_artifacts.read_json(paths.timeline_json)]
    semantic_scenes = tuple(chapter.semantic_scene("rerender")
                            for chapter in saved_timeline)
    timeline_spans = tuple(chapter.timeline_span() for chapter in saved_timeline)
    del saved_timeline
    media_scenes = project_artifacts.read_json(paths.media_json)
    render_plan = pipeline_render_stage.SceneRenderPlan.from_persisted_rows(
        media_scenes)
    try:
        meta = project_artifacts.read_json(paths.metadata_json)
        idea = meta.get("input", slug)
    except (json.JSONDecodeError, FileNotFoundError):
        meta = {}
        idea = slug
    saved_audio = meta.get("audio_request") or meta.get("audio")
    if saved_audio:
        audio_composition.apply_audio_request(cfg, saved_audio)
    else:
        cfg.audio_enabled = False
        cfg.music_mode = "none"
        cfg.music_transitions = "none"
        cfg.sfx_library_enabled = False
        cfg.music_auto_fill = cfg.sfx_auto_fill = False
    project_genre = str(meta.get("genre") or cfg.genre or "")
    transition_mode = audio_composition.transition_mode(cfg)

    progress_started: dict[str, float] = {}

    def emit(label: str, status: str = "…") -> None:
        set_log_stage(label)
        if status == "…":
            progress_started[label] = time.monotonic()
            run_event("stage_started", label)
        else:
            elapsed = round(time.monotonic() - progress_started.pop(label,
                                                                     time.monotonic()), 2)
            if status == "OK":
                status = f"OK ({elapsed:.1f}s)"
            run_event("stage_finished", label, status=status,
                      duration_seconds=elapsed)
        if on_progress:
            on_progress(label, status)

    emit("Validando áudio")
    shutil.copy(audio_src, paths.human_wav) if (
        force or not os.path.isfile(paths.human_wav)) else None
    human_dur = ff.probe_duration(paths.human_wav)
    silent_dur = ff.probe_duration(paths.silent_mp4)
    warnings = []
    ratio = human_dur / silent_dur if silent_dur > 0 else 1.0
    if ratio > 2.0 or ratio < 0.5:
        msg = (f"áudio humano ({human_dur:.1f}s) muito diferente do "
               f"silencioso ({silent_dur:.1f}s)")
        warnings.append(msg)
        print(f"AVISO: {msg}", file=sys.stderr)
    emit("Validando áudio", "OK")

    emit("Transcrevendo")
    if force or not os.path.isfile(paths.transcription_json):
        whisper_lang = "en" if str(cfg.language or "").lower().startswith("en") else "pt"
        words = transcribe_stage.transcribe(paths.human_wav,
                                            cfg.whisper_model, metrics=metrics,
                                            language=whisper_lang)
        project_artifacts.write_json(paths.transcription_json, words)
    else:
        words = project_artifacts.read_json(paths.transcription_json)
    run_event("provider" if metrics.whisper_calls else "cache",
              f"Transcrição: {'faster-whisper/' + cfg.whisper_model if metrics.whisper_calls else 'cache'}; "
              f"{len(words)} palavra(s)", operation="transcription",
              model=cfg.whisper_model, words=len(words),
              cache=not bool(metrics.whisper_calls))
    emit("Transcrevendo", "OK")

    emit("Legendando")
    _perfil = editorial_stage.get((meta or {}).get("genre", ""))
    _pac = _perfil.pacing if _perfil is not None else None
    cue_count = subs_stage.write_subtitles(
        "", human_dur, paths.subs_srt, paths.subs_ass,
        cfg.width, cfg.height, cfg.sub_font_size,
        subs_stage.safe_subtitle_margin(cfg.height, cfg.sub_margin_v),
        words=words, cache_dir=cfg.cache_dir,
        max_words=min(5, _pac.caption_max_words if _pac is not None else 5),
        highlight="word", upper=False, karaoke=True)
    run_event("result", f"Legendas: {cue_count} cue(s)",
              operation="subtitles", cues=cue_count)
    emit("Legendando", "OK")

    emit("Ajustando visual")
    diff = human_dur - silent_dur
    silent = paths.silent_mp4
    visual_timeline = None
    if os.path.isfile(paths.visual_json):
        try:
            visual_timeline = project_artifacts.read_json(paths.visual_json)
        except json.JSONDecodeError:
            visual_timeline = None
    if abs(diff) <= 0.3:
        pass  # compatível: reusa o silencioso
    elif diff > 0:
        # Áudio mais longo: estende a ÚLTIMA cena (nunca corta a fala).
        adj = os.path.join(paths.root, "render", "silent_adj.mp4")
        render_spans = timeline_spans
        if visual_timeline:
            last = timeline_spans[-1]
            final_span = TimelineSpan(
                last.scene_id, last.duration_estimate + diff,
                last.start, round(last.end + diff, 3))
            timeline_spans = (*timeline_spans[:-1], final_span)
            render_spans = timeline_spans
            project_artifacts.write_json(paths.timeline_json, [
                Chapter.from_semantic_scene(scene, timing=span).to_dict()
                for scene, span in zip(semantic_scenes, timeline_spans)])
            visual_timeline = visual_timeline_stage.retime_visual_timeline(
                visual_timeline, timeline_spans)
            project_artifacts.write_json(paths.visual_json, visual_timeline)
            pipeline_render_stage.build_silent_visual(
                                 semantic_scenes, timeline_spans,
                                 visual_timeline, idea, paths,
                                 cfg, adj, transitions=pipeline_render_stage.genre_transitions(
                                      semantic_scenes, project_genre, transition_mode),
                                 kinds=pipeline_render_stage.genre_transition_kinds(
                                      semantic_scenes, project_genre, transition_mode))
        else:
            last = timeline_spans[-1]
            render_spans = (*timeline_spans[:-1], TimelineSpan(
                last.scene_id, last.duration_estimate + diff,
                last.start, last.end + diff))
            pipeline_render_stage.build_silent(
                           semantic_scenes, render_spans, render_plan,
                           idea, paths,
                           cfg, adj, transitions=pipeline_render_stage.genre_transitions(
                               semantic_scenes, project_genre, transition_mode),
                           kinds=pipeline_render_stage.genre_transition_kinds(
                               semantic_scenes, project_genre, transition_mode))
        silent = adj
        warnings.append(f"última cena estendida +{diff:.1f}s p/ caber o áudio")
    else:
        warnings.append(f"áudio {abs(diff):.1f}s mais curto — cauda cortada")
    emit("Ajustando visual", "OK")

    emit("Merge final")
    total = round(human_dur + 0.5, 2)
    metrics.visual_plan(timeline_spans,
                        MediaMetricsInput.from_persisted_rows(media_scenes),
                        BEAT_SECONDS, visual_timeline,
                        rendered_duration=total)
    human_wav = paths.human_wav
    sfx_path = None
    events = audio_composition.sfx_events(visual_timeline or [])
    script_text = project_artifacts.read_text(paths.script_txt) if os.path.isfile(paths.script_txt) else ""
    video_title = (meta.get("video_title") or "").strip()
    audio_plan = audio_selection.resolve_audio(
        cfg, project_genre, audio_seed(slug, video_title or idea, script_text),
        video_title or idea, script_text, events,
        meta.get("audio") or meta.get("audio_request"))
    warnings.extend(audio_plan["warnings"])
    if visual_timeline and cfg.visual_sfx:
        sfx_path = audio_composition.sfx_track(visual_timeline, total, paths)
        if sfx_path:
            human_wav = audio_composition.narration_with_sfx(paths.human_wav, sfx_path,
                                            total, paths)
    video_title = video_title or None
    music_asset = audio_plan.get("music_asset")
    render_info = render_stage.burn_final(
        silent, paths.subs_ass, human_wav, paths.final_mp4, cfg, total,
        title=video_title,
        title_fontfile=pipeline_render_stage.title_fontfile(cfg,
                                       project_genre),
        music_path=str(music_asset.get("path")) if music_asset else None,
        music_gain_db=cfg.music_gain_db,
        music_ducking=cfg.music_ducking,
        final_fade=audio_composition.final_audio_fade(project_genre, transition_mode))
    run_event("result", f"Render: {render_info['backend']} / "
              f"{render_info['encoder']}; {render_info['duration']:.1f}s",
              operation="render", backend=render_info["backend"],
              encoder=render_info["encoder"],
              duration_seconds=round(render_info["duration"], 2))
    audio_composition.mark_audio_used(cfg, audio_plan)
    emit("Merge final", "OK")

    try:
        meta = project_artifacts.read_json(paths.metadata_json)
    except (json.JSONDecodeError, FileNotFoundError):
        meta = {}
    meta.update({
        "narration": "human",
        "duration_actual": round(render_info["duration"], 2),
        "audio_duration": round(human_dur, 2),
        "subtitle_cues": cue_count,
        "subtitle_source": "whisper",
        "transcription_model": f"faster-whisper/{cfg.whisper_model}",
        "audio": audio_plan["metadata"],
        "visual_transition_signature": pipeline_render_stage.transition_signature(
            semantic_scenes, timeline_spans, project_genre, transition_mode,
            {"insertions": cfg.visual_insertions,
             "insert_style": cfg.visual_insert_style,
             "insert_gain_db": cfg.visual_insert_gain_db,
             "visual_sfx": cfg.visual_sfx}),
        "visual_transitions": {
            "genre": project_genre, "mode": transition_mode,
            "boundary_durations": pipeline_render_stage.genre_transitions(
                semantic_scenes, project_genre, transition_mode),
            "final_fade": audio_composition.final_audio_fade(
                project_genre, transition_mode),
        },
        "finalize_warnings": warnings,
        "warnings": sorted(set(meta.get("warnings", []) + warnings)),
        "processing_time_seconds": round(time.monotonic() - started, 2),
        "execution_log": current_log_path(),
    })
    meta.setdefault("artifacts", {})["video"] = paths.final_mp4
    meta["artifacts"]["human_audio"] = paths.human_wav
    meta["artifacts"]["transcription"] = paths.transcription_json
    if sfx_path:
        meta["artifacts"]["sfx"] = sfx_path
    if music_asset:
        meta["artifacts"]["music"] = music_asset["path"]
    stage_times = {"finalize": round(time.monotonic() - started, 2)}
    return pipeline_metadata_stage.persist_run_metadata(
        meta, paths.metadata_json, metrics, stage_times, cfg.metrics_dir,
        project_artifacts.write_json, started, started)
