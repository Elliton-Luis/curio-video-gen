"""Orquestração do pipeline (PRD §4, §15, §16, §19).

Fluxo A (narração IA): roteiro → cenas → mídia → narração → legendas → montagem.
Fluxo B (narração humana): roteiro → cenas → mídia → timeline → silencioso
→ teleprompter; depois `finalize_project` com o áudio humano.
Tudo cacheável por artefato; mídia sem resultado vira fallback com aviso.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import ffmpeg as ff
from .config import CurioConfig
from .media import download_asset, get_providers
from .media.providers import MediaAsset, MediaError
from .slug import slugify
from .stages import render as render_stage
from .stages import scenes as scenes_stage
from .stages import script as script_stage
from .stages import subs as subs_stage
from .stages import teleprompter as tele_stage
from .stages import transcribe as transcribe_stage
from .stages import tts as tts_stage
from .stages.scenes import Chapter

STAGES_AI = ["roteiro", "cenas", "mídia", "narração", "legendas", "montagem"]
STAGES_HUMAN = ["roteiro", "cenas", "mídia", "timeline", "silencioso",
                "teleprompter"]


@dataclass
class VideoPaths:
    root: str
    script_txt: str
    chapters_json: str
    media_json: str
    narration_wav: str
    words_json: str
    timeline_json: str
    subs_srt: str
    subs_ass: str
    tele_ass: str
    tele_mp4: str
    silent_mp4: str
    human_wav: str
    transcription_json: str
    final_mp4: str
    metadata_json: str


def video_paths(out_dir: str, slug: str) -> VideoPaths:
    root = os.path.join(out_dir, slug)
    return VideoPaths(
        root=root,
        script_txt=os.path.join(root, "script", "script.txt"),
        chapters_json=os.path.join(root, "script", "chapters.json"),
        media_json=os.path.join(root, "media", "media.json"),
        narration_wav=os.path.join(root, "audio", "narration.wav"),
        words_json=os.path.join(root, "audio", "words.json"),
        timeline_json=os.path.join(root, "timeline", "timeline.json"),
        subs_srt=os.path.join(root, "subtitles", "subs.srt"),
        subs_ass=os.path.join(root, "subtitles", "subs.ass"),
        tele_ass=os.path.join(root, "teleprompter", "teleprompter.ass"),
        tele_mp4=os.path.join(root, "teleprompter", "teleprompter.mp4"),
        silent_mp4=os.path.join(root, "render", "silent.mp4"),
        human_wav=os.path.join(root, "audio", "human.wav"),
        transcription_json=os.path.join(root, "audio", "transcription.json"),
        final_mp4=os.path.join(root, "render", "final.mp4"),
        metadata_json=os.path.join(root, "metadata.json"),
    )


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


def _load_chapters(paths: VideoPaths) -> list[Chapter]:
    return [Chapter.from_dict(d) for d in _read_json(paths.chapters_json)]


def _query_terms(query: str) -> list[str]:
    stop = {"the", "and", "with", "from", "into", "para", "uma", "para"}
    return [t.lower() for t in query.replace(",", " ").split()
            if len(t) > 2 and t.lower() not in stop]


def _relevance(query: str, asset: MediaAsset) -> int:
    haystack = f"{asset.title}".lower()
    return sum(1 for term in _query_terms(query) if term in haystack)


def _fetch_media(chapters: list[Chapter], cfg: CurioConfig,
                 paths: VideoPaths) -> tuple[list[dict], list[str]]:
    """Busca e baixa um asset por cena. Falha vira fallback com aviso."""
    providers = get_providers(cfg)
    scenes, warnings = [], []
    for ch in chapters:
        # Candidatos de todas as consultas, ordenados por relevância
        # (sobreposição consulta↔título) — evita associações falsas.
        ranked: list[tuple[int, str, MediaAsset]] = []
        seen = set()
        for query in ch.visual_queries:
            for prov in providers:
                try:
                    candidates = prov.search(query)
                except MediaError as exc:
                    print(f"AVISO: {exc} — tentando próxima fonte.",
                          file=sys.stderr)
                    continue
                for cand in candidates:
                    if cand.asset_id in seen:
                        continue
                    seen.add(cand.asset_id)
                    ranked.append((_relevance(query, cand), query, cand))
        ranked.sort(key=lambda r: -r[0])
        asset = None
        for _score, _q, cand in ranked:
            try:
                asset = download_asset(cand, cfg.cache_dir)
                break
            except MediaError as exc:
                print(f"AVISO: {exc} — tentando próximo asset.",
                      file=sys.stderr)
        if asset is None:
            msg = (f"cena {ch.id}: sem mídia adequada "
                   f"({', '.join(ch.visual_queries) or 'sem consultas'}) — fallback")
            warnings.append(msg)
            print(f"AVISO: {msg}", file=sys.stderr)
        scenes.append({"chapter_id": ch.id,
                       "asset": asset.to_dict() if asset else None})
    return scenes, warnings


def _scene_segment(ch: Chapter, asset_dict: dict | None, idea: str,
                   duration: float, paths: VideoPaths, cfg: CurioConfig,
                   variant: int) -> str:
    seg = os.path.join(paths.root, "render", "segments",
                       f"scene{ch.id}_{duration:.1f}s.mp4")
    if os.path.isfile(seg):
        return seg
    os.makedirs(os.path.dirname(seg), exist_ok=True)
    if asset_dict and asset_dict.get("local_path"):
        local = asset_dict["local_path"]
        if asset_dict.get("kind") == "video":
            return render_stage.render_video_segment(local, duration, seg, cfg)
        if os.path.isfile(local):
            return render_stage.render_image_segment(local, duration, seg,
                                                     cfg, variant)
    return render_stage.render_fallback_segment(
        duration, seg, cfg, render_stage._wrap_title(idea))


def _build_silent(chapters: list[Chapter], media_scenes: list[dict], idea: str,
                  durations: list[float], paths: VideoPaths,
                  cfg: CurioConfig, out_path: str) -> str:
    assets = {s["chapter_id"]: s["asset"] for s in media_scenes}
    segs = []
    for i, (ch, dur) in enumerate(zip(chapters, durations)):
        segs.append(_scene_segment(ch, assets.get(ch.id), idea, round(dur, 1),
                                   paths, cfg, variant=i))
    return render_stage.concat_copy(segs, out_path)


def _base_metadata(idea: str, slug: str, cfg: CurioConfig, script_text: str,
                   script_source: str, chapters: list[Chapter],
                   scenes_source: str, media_scenes: list[dict],
                   warnings: list[str], stage_times: dict,
                   started: float) -> dict:
    return {
        "title": idea.strip(),
        "input": idea,
        "slug": slug,
        "duration_target": cfg.duration_target,
        "script_source": script_source,
        "script_chars": len(script_text),
        "scenes_source": scenes_source,
        "chapters": [c.to_dict() for c in chapters],
        "media": media_scenes,
        "warnings": warnings,
        "width": cfg.width,
        "height": cfg.height,
        "fps": cfg.fps,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processing_time_seconds": round(time.monotonic() - started, 2),
        "stage_times": stage_times,
        "pipeline_version": "scenes-0.2",
    }


def run_pipeline(idea: str, cfg: CurioConfig, slug: str | None = None,
                 force: bool = False, narration: str = "ai",
                 on_progress=None) -> dict:
    started = time.monotonic()
    stage_times: dict[str, float] = {}
    warnings: list[str] = []
    stages = STAGES_HUMAN if narration == "human" else STAGES_AI

    def emit(idx: int, label: str, status: str = "…") -> None:
        if on_progress:
            on_progress(idx, len(stages), label, status)

    slug = slug or slugify(idea)
    paths = video_paths(cfg.out_dir, slug)
    for d in ("script", "audio", "subtitles", "assets", "render",
              "media", "timeline", "teleprompter"):
        os.makedirs(os.path.join(paths.root, d), exist_ok=True)

    # [1/6] Roteiro
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

    # [2/6] Cenas
    t0 = time.monotonic()
    emit(2, "Interpretando cenas")
    if not force and os.path.isfile(paths.chapters_json):
        chapters = _load_chapters(paths)
        scenes_source = "cache"
    else:
        chapters, scenes_source = scenes_stage.build_chapters(script_text, cfg)
        _write_json(paths.chapters_json, [c.to_dict() for c in chapters])
    stage_times["scenes"] = round(time.monotonic() - t0, 2)
    emit(2, "Interpretando cenas", "OK")

    # [3/6] Mídia
    t0 = time.monotonic()
    emit(3, "Buscando mídia")
    media_scenes = None
    if not force and os.path.isfile(paths.media_json):
        try:
            saved = _read_json(paths.media_json)
            if ([s["chapter_id"] for s in saved] ==
                    [c.id for c in chapters] and all(
                        s["asset"] is None or os.path.isfile(
                            s["asset"].get("local_path", ""))
                        for s in saved)):
                media_scenes = saved
        except (json.JSONDecodeError, KeyError):
            media_scenes = None
    if media_scenes is None:
        media_scenes, media_warnings = _fetch_media(chapters, cfg, paths)
        warnings.extend(media_warnings)
        _write_json(paths.media_json, media_scenes)
    stage_times["media"] = round(time.monotonic() - t0, 2)
    emit(3, "Buscando mídia",
         "AVISO" if any(s["asset"] is None for s in media_scenes) else "OK")

    if narration == "human":
        return _human_prep(idea, slug, cfg, paths, script_text, script_source,
                           chapters, scenes_source, media_scenes, warnings,
                           stage_times, started, emit)

    # [4/6] Narração (IA) — timestamps reais via WordBoundary
    t0 = time.monotonic()
    emit(4, "Gerando narração")
    words = None
    if (not force and os.path.isfile(paths.narration_wav)
            and os.path.isfile(paths.words_json)):
        audio_duration = ff.probe_duration(paths.narration_wav)
        words = _read_json(paths.words_json)
        tts_info = {"provider": cfg.tts_provider, "voice": cfg.tts_voice,
                    "speed": cfg.tts_speed, "reused": True}
    else:
        res = tts_stage.synthesize(script_text, paths.narration_wav,
                                   cfg.tts_provider, cfg.tts_voice,
                                   cfg.tts_speed, cfg.duration_target,
                                   words_path=paths.words_json)
        audio_duration = res.duration
        words = res.words
        tts_info = {"provider": res.provider, "voice": res.voice,
                    "speed": res.speed, "reused": False}
    stage_times["tts"] = round(time.monotonic() - t0, 2)
    emit(4, "Gerando narração", "OK")

    # Timeline real: capítulos alinhados aos boundaries (sem offset artificial)
    try:
        chapters = scenes_stage.apply_timings(chapters, words or [])
        timed_source = "wordboundary"
    except (ValueError, IndexError) as exc:
        print(f"AVISO: {exc} — timeline proporcional.", file=sys.stderr)
        warnings.append(f"timeline proporcional ({exc})")
        cursor = (words[0]["start"] if words else 0.15) if words else 0.15
        total_w = sum(len(c.narration.split()) for c in chapters) or 1
        for ch in chapters:
            share = audio_duration * len(ch.narration.split()) / total_w
            ch.start, ch.end = cursor, cursor + share
            cursor = ch.end
        timed_source = "proporcional"
    # Costura: pausas entre falas pertencem às cenas (nada de buraco visual);
    # último capítulo cobre até o fim do áudio.
    chapters[0].start = 0.0
    for prev, nxt in zip(chapters, chapters[1:]):
        mid = round((prev.end + nxt.start) / 2, 3)
        prev.end = nxt.start = mid
    chapters[-1].end = round(audio_duration, 3)
    _write_json(paths.timeline_json, [c.to_dict() for c in chapters])

    # [5/6] Legendas (reais quando há boundaries)
    t0 = time.monotonic()
    emit(5, "Sincronizando legendas")
    if force or not (os.path.isfile(paths.subs_srt)
                     and os.path.isfile(paths.subs_ass)):
        cue_count = subs_stage.write_subtitles(
            script_text, audio_duration, paths.subs_srt, paths.subs_ass,
            cfg.width, cfg.height, cfg.sub_font_size, cfg.sub_margin_v,
            words=words if tts_info["provider"] == "edge-tts" else None)
    else:
        cue_count = _read(paths.subs_srt).count("-->")
    stage_times["subs"] = round(time.monotonic() - t0, 2)
    emit(5, "Sincronizando legendas", "OK")

    # [6/6] Montagem dinâmica + final
    t0 = time.monotonic()
    emit(6, "Montando vídeo")
    durations = [max(0.5, c.end - c.start) for c in chapters]
    total = round(audio_duration + 0.8, 2)
    if not force and os.path.isfile(paths.final_mp4):
        video_duration = ff.probe_duration(paths.final_mp4)
        render_info = {"backend": "cache", "encoder": "cache",
                       "duration": video_duration, "path": paths.final_mp4}
    else:
        silent = paths.silent_mp4
        if force or not os.path.isfile(silent):
            _build_silent(chapters, media_scenes, idea, durations, paths,
                          cfg, silent)
        render_info = render_stage.burn_final(
            silent, paths.subs_ass, paths.narration_wav, paths.final_mp4,
            cfg, total)
        video_duration = render_info["duration"]
    stage_times["render"] = round(time.monotonic() - t0, 2)
    emit(6, "Montando vídeo", "OK")

    metadata = _base_metadata(idea, slug, cfg, script_text, script_source,
                              chapters, scenes_source, media_scenes, warnings,
                              stage_times, started)
    metadata.update({
        "narration": "ai",
        "timeline_source": timed_source,
        "duration_actual": round(video_duration, 2),
        "audio_duration": round(audio_duration, 2),
        "subtitle_cues": cue_count,
        "subtitle_source": ("wordboundary" if words and
                            tts_info["provider"] == "edge-tts"
                            else "proporcional"),
        "tts_provider": tts_info["provider"],
        "tts_voice": tts_info["voice"],
        "tts_speed": tts_info["speed"],
        "tts_reused": tts_info["reused"],
        "render_backend": render_info["backend"],
        "render_encoder": render_info["encoder"],
        "artifacts": {
            "script": paths.script_txt,
            "chapters": paths.chapters_json,
            "media": paths.media_json,
            "audio": paths.narration_wav,
            "words": paths.words_json,
            "timeline": paths.timeline_json,
            "subtitles": paths.subs_srt,
            "subtitles_ass": paths.subs_ass,
            "silent": paths.silent_mp4,
            "video": paths.final_mp4,
        },
    })
    _write_json(paths.metadata_json, metadata)
    stage_times["finalize"] = 0.0
    metadata["stage_times"] = stage_times
    return metadata


def _human_prep(idea: str, slug: str, cfg: CurioConfig, paths: VideoPaths,
                script_text: str, script_source: str, chapters: list[Chapter],
                scenes_source: str, media_scenes: list[dict],
                warnings: list[str], stage_times: dict, started: float,
                emit) -> dict:
    # [4/6] Timeline estimada por WPM (só para leitura — nunca sincronia final)
    t0 = time.monotonic()
    emit(4, "Estimando timeline")
    cursor = 0.0
    for ch in chapters:
        ch.duration_estimate = scenes_stage.estimate_duration(
            ch.narration, cfg.teleprompter_wpm)
        ch.start, ch.end = cursor, cursor + ch.duration_estimate
        cursor = ch.end
    estimated_total = round(cursor, 2)
    _write_json(paths.timeline_json, [c.to_dict() for c in chapters])
    stage_times["timeline"] = round(time.monotonic() - t0, 2)
    emit(4, "Estimando timeline", "OK")

    # [5/6] Vídeo silencioso
    t0 = time.monotonic()
    emit(5, "Montando silencioso")
    durations = [c.end - c.start for c in chapters]
    _build_silent(chapters, media_scenes, idea, durations, paths, cfg,
                  paths.silent_mp4)
    stage_times["silent"] = round(time.monotonic() - t0, 2)
    emit(5, "Montando silencioso", "OK")

    # [6/6] Teleprompter (texto grande sobre cópia do silencioso)
    t0 = time.monotonic()
    emit(6, "Gerando teleprompter")
    tele_cues = tele_stage.write_teleprompter_ass(
        chapters, paths.tele_ass, cfg.width, cfg.height)
    tele_info = render_stage.burn_final(
        paths.silent_mp4, paths.tele_ass, None, paths.tele_mp4,
        cfg, estimated_total)
    stage_times["teleprompter"] = round(time.monotonic() - t0, 2)
    emit(6, "Gerando teleprompter", "OK")

    metadata = _base_metadata(idea, slug, cfg, script_text, script_source,
                              chapters, scenes_source, media_scenes, warnings,
                              stage_times, started)
    metadata.update({
        "narration": "human-pending",
        "duration_actual": estimated_total,
        "teleprompter_wpm": cfg.teleprompter_wpm,
        "teleprompter_cues": tele_cues,
        "artifacts": {
            "script": paths.script_txt,
            "chapters": paths.chapters_json,
            "media": paths.media_json,
            "timeline": paths.timeline_json,
            "silent": paths.silent_mp4,
            "teleprompter": paths.tele_mp4,
            "teleprompter_ass": paths.tele_ass,
        },
    })
    _write_json(paths.metadata_json, metadata)
    metadata["stage_times"] = stage_times
    return metadata


def _probe_streams(path: str) -> list[dict]:
    import json as _json
    proc = ff.run([ff.FFPROBE, "-v", "error", "-show_entries",
                   "stream=codec_type,duration", "-of", "json", path])
    if proc.returncode != 0:
        raise ff.FFMpegError(f"ffprobe falhou em {path}: {proc.stderr.strip()}")
    return (_json.loads(proc.stdout).get("streams") or [])


def finalize_project(slug: str, audio_src: str, cfg: CurioConfig,
                     force: bool = False, on_progress=None) -> dict:
    """Une áudio humano ao vídeo silencioso: transcreve, legenda, merge."""
    started = time.monotonic()
    paths = video_paths(cfg.out_dir, slug)
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

    chapters = _load_chapters(paths)
    media_scenes = _read_json(paths.media_json)
    try:
        meta = _read_json(paths.metadata_json)
        idea = meta.get("input", slug)
    except (json.JSONDecodeError, FileNotFoundError):
        idea = slug

    def emit(label: str, status: str = "…") -> None:
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
        words = transcribe_stage.transcribe(paths.human_wav,
                                            cfg.whisper_model)
        _write_json(paths.transcription_json, words)
    else:
        words = _read_json(paths.transcription_json)
    emit("Transcrevendo", "OK")

    emit("Legendando")
    cue_count = subs_stage.write_subtitles(
        "", human_dur, paths.subs_srt, paths.subs_ass,
        cfg.width, cfg.height, cfg.sub_font_size, cfg.sub_margin_v,
        words=words)
    emit("Legendando", "OK")

    emit("Ajustando visual")
    diff = human_dur - silent_dur
    silent = paths.silent_mp4
    if abs(diff) <= 0.3:
        pass  # compatível: reusa o silencioso
    elif diff > 0:
        # Áudio mais longo: estende a ÚLTIMA cena (nunca corta a fala).
        adj = os.path.join(paths.root, "render", "silent_adj.mp4")
        durations = [c.end - c.start for c in chapters]
        durations[-1] += diff
        _build_silent(chapters, media_scenes, idea, durations, paths, cfg, adj)
        silent = adj
        warnings.append(f"última cena estendida +{diff:.1f}s p/ caber o áudio")
    else:
        warnings.append(f"áudio {abs(diff):.1f}s mais curto — cauda cortada")
    emit("Ajustando visual", "OK")

    emit("Merge final")
    total = round(human_dur + 0.5, 2)
    render_info = render_stage.burn_final(
        silent, paths.subs_ass, paths.human_wav, paths.final_mp4, cfg, total)
    emit("Merge final", "OK")

    try:
        meta = _read_json(paths.metadata_json)
    except (json.JSONDecodeError, FileNotFoundError):
        meta = {}
    meta.update({
        "narration": "human",
        "duration_actual": round(render_info["duration"], 2),
        "audio_duration": round(human_dur, 2),
        "subtitle_cues": cue_count,
        "subtitle_source": "whisper",
        "transcription_model": f"faster-whisper/{cfg.whisper_model}",
        "finalize_warnings": warnings,
        "warnings": sorted(set(meta.get("warnings", []) + warnings)),
        "processing_time_seconds": round(time.monotonic() - started, 2),
    })
    meta.setdefault("artifacts", {})["video"] = paths.final_mp4
    meta["artifacts"]["human_audio"] = paths.human_wav
    meta["artifacts"]["transcription"] = paths.transcription_json
    _write_json(paths.metadata_json, meta)
    return meta
