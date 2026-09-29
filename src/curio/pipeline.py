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
from .metrics import RunMetrics, backfill_from_metadata
from .slug import slugify
from .stages import render as render_stage
from .stages import nvidia as nvidia_stage
from .stages import scenes as scenes_stage
from .stages import script as script_stage
from .stages import subs as subs_stage
from .stages import teleprompter as tele_stage
from .stages import transcribe as transcribe_stage
from .stages import tts as tts_stage
from .stages import visual as visual_stage
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
    visual_json: str
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
        visual_json=os.path.join(root, "timeline", "visual_timeline.json"),
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
    # Diretório defensivo: nada apaga output/, mas limpeza externa
    # concorrente não deve derrubar o run com FileNotFoundError.
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
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
                 paths: VideoPaths, metrics=None) -> tuple[list[dict], list[str]]:
    """Busca e baixa um asset por cena. Falha vira fallback com aviso."""
    providers = get_providers(cfg)
    search_memo: dict[tuple[str, str], list] = {}
    scenes, warnings = [], []
    for ch in chapters:
        # Candidatos de todas as consultas, ordenados por relevância
        # (sobreposição consulta↔título) — evita associações falsas.
        ranked: list[tuple[int, str, MediaAsset]] = []
        seen = set()
        for query in ch.visual_queries:
            for prov in providers:
                memo_key = (prov.name, query)
                if memo_key not in search_memo:
                    try:
                        search_memo[memo_key] = prov.search(query, metrics=metrics)
                    except MediaError as exc:
                        print(f"AVISO: {exc} — tentando próxima fonte.",
                              file=sys.stderr)
                        search_memo[memo_key] = []
                for cand in search_memo[memo_key]:
                    if cand.asset_id in seen:
                        continue
                    seen.add(cand.asset_id)
                    ranked.append((_relevance(query, cand), query, cand))
        ranked.sort(key=lambda r: -r[0])
        # Gate de relevância: escore 0 = título sem nada da consulta
        # (ex.: foto aleatória) — fallback honesto em vez de associação falsa.
        ranked = [r for r in ranked if r[0] > 0]
        asset = None
        for _score, _q, cand in ranked:
            try:
                asset = download_asset(cand, cfg.cache_dir, metrics)
                break
            except MediaError as exc:
                print(f"AVISO: {exc} — tentando próximo asset.",
                      file=sys.stderr)
        if asset is None:
            msg = (f"cena {ch.id}: sem mídia relevante "
                   f"({', '.join(ch.visual_queries) or 'sem consultas'}) — fallback")
            warnings.append(msg)
            print(f"AVISO: {msg}", file=sys.stderr)
        scenes.append({"chapter_id": ch.id,
                       "asset": asset.to_dict() if asset else None,
                       "reused_from": None})
    _resolve_reuse(scenes)
    return scenes, warnings


def _resolve_reuse(scenes: list[dict]) -> None:
    """Garantia de imagem do início ao fim: cena sem asset reusa a imagem
    relevante mais próxima (com outro movimento Ken Burns) antes de cair no
    gradiente. Só o gradiente resta se NENHUMA cena tiver mídia."""
    have = [s for s in scenes if s["asset"]]
    if not have:
        return
    for s in scenes:
        if s["asset"] is not None:
            continue
        cid = s["chapter_id"]
        nearest = min(have, key=lambda h: (abs(h["chapter_id"] - cid),
                                           0 if h["chapter_id"] < cid else 1))
        s["asset"] = nearest["asset"]
        s["reused_from"] = nearest["chapter_id"]
        print(f"AVISO: cena {cid} reusa imagem da cena "
              f"{nearest['chapter_id']} (sem mídia própria).", file=sys.stderr)


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


def _visual_segment(trecho: dict, idea: str, duration: float,
                    paths: VideoPaths, cfg: CurioConfig,
                    variant: int) -> str:
    """Um segmento do modo roteiro-pronto: colagem se houver 2+ fotos."""
    images = [dict(img) for img in trecho.get("images", [])]
    images = [im for im in images
              if im.get("local_path") and os.path.isfile(im["local_path"])]
    seg = os.path.join(paths.root, "render", "segments",
                       f"scene{trecho['chapter_id']}_visual_{duration:.1f}s.mp4")
    if os.path.isfile(seg):
        return seg
    os.makedirs(os.path.dirname(seg), exist_ok=True)
    if len(images) >= 2:
        return render_stage.render_collage_segment(images, duration, seg,
                                                   cfg, variant)
    asset = images[0] if images else None
    return _scene_segment(
        Chapter(id=trecho["chapter_id"], narration=trecho.get("narration", ""),
                duration_estimate=duration),
        {"local_path": asset["local_path"],
         "kind": asset.get("kind", "image")} if asset else None,
        idea, duration, paths, cfg, variant)


def _build_silent_visual(chapters: list[Chapter], visual_timeline: list[dict],
                         idea: str, paths: VideoPaths,
                         cfg: CurioConfig, out_path: str) -> str:
    trechos = {t["chapter_id"]: t for t in visual_timeline}
    segs = []
    for i, ch in enumerate(chapters):
        t = trechos.get(ch.id, {})
        dur = round(max(0.5, ch.end - ch.start), 1)
        segs.append(_visual_segment(
            {"chapter_id": ch.id, "narration": ch.narration,
             "images": t.get("images", [])} if t else
            {"chapter_id": ch.id, "narration": ch.narration, "images": []},
            idea, dur, paths, cfg, variant=i))
    return render_stage.concat_copy(segs, out_path)


def _write_visual_timeline(chapters: list[Chapter], media_scenes: list[dict],
                           paths: VideoPaths, slug: str,
                           overlap_cap: float, sfx: bool) -> list[dict]:
    vt = visual_stage.build_visual_timeline(chapters, media_scenes,
                                            overlap_cap, seed=slug, sfx=sfx)
    _write_json(paths.visual_json, vt)
    print(f"Timeline visual: {visual_stage.visual_summary(vt)}")
    return vt


def _sfx_track_for(visual_timeline: list[dict], total: float,
                   paths: VideoPaths) -> str | None:
    """Gera audio/sfx.wav a partir dos eventos da timeline (ou None)."""
    events = [img["sfx"] for t in visual_timeline for img in t.get("images", [])
              if isinstance(img.get("sfx"), dict)]
    if not events:
        return None
    out = os.path.join(paths.root, "audio", "sfx.wav")
    return render_stage.build_sfx_track(events, total, out)


def _narration_with_sfx(wav_path: str, sfx_path: str | None, total: float,
                        paths: VideoPaths) -> str:
    """Mistura o SFX na narração (sem tocar seu volume) ou devolve o original."""
    if not sfx_path:
        return wav_path
    out = os.path.join(paths.root, "audio", "mixed.wav")
    return render_stage.mix_sfx(wav_path, sfx_path, out, total)


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
                 on_progress=None, provided_script: str | None = None,
                 max_images: int = 1,
                 visual_overlap: float | None = None) -> dict:
    started = time.monotonic()
    stage_times: dict[str, float] = {}
    warnings: list[str] = []
    stages = STAGES_HUMAN if narration == "human" else STAGES_AI
    script_mode = provided_script is not None
    max_images = max(1, min(5, int(max_images or 1)))
    overlap_cap = float(cfg.visual_overlap if visual_overlap is None
                        else visual_overlap)

    def emit(idx: int, label: str, status: str = "…") -> None:
        if on_progress:
            on_progress(idx, len(stages), label, status)

    slug = slug or slugify(idea)
    paths = video_paths(cfg.out_dir, slug)
    metrics = RunMetrics(slug, idea, narration)
    for d in ("script", "audio", "subtitles", "assets", "render",
              "media", "timeline", "teleprompter"):
        os.makedirs(os.path.join(paths.root, d), exist_ok=True)

    # [1/6] Roteiro (modo roteiro-pronto: usa o texto verbatim, nunca gera)
    t0 = time.monotonic()
    emit(1, "Lendo roteiro pronto" if script_mode else "Gerando roteiro")
    force_after_script = force
    if script_mode:
        assert provided_script is not None
        script_text = provided_script.strip()
        if not script_text:
            raise ValueError("roteiro vazio — nada para produzir")
        script_source = "provided"
        cached = _read(paths.script_txt) if os.path.isfile(paths.script_txt) else None
        if cached != script_text:
            with open(paths.script_txt, "w", encoding="utf-8") as fh:
                fh.write(script_text)
            if cached is not None and not force:
                print("AVISO: roteiro fornecido mudou — refazendo cenas e mídia.",
                      file=sys.stderr)
                force_after_script = True
    elif not force and os.path.isfile(paths.script_txt):
        script_text, script_source = _read(paths.script_txt), "cache"
    else:
        script_text, script_source = script_stage.generate_script(idea, cfg, metrics)
        with open(paths.script_txt, "w", encoding="utf-8") as fh:
            fh.write(script_text)
    stage_times["script"] = round(time.monotonic() - t0, 2)
    emit(1, "Lendo roteiro pronto" if script_mode else "Gerando roteiro", "OK")

    # [2/6] Cenas
    t0 = time.monotonic()
    emit(2, "Interpretando cenas")
    if not force_after_script and os.path.isfile(paths.chapters_json):
        chapters = _load_chapters(paths)
        scenes_source = "cache"
        if script_mode:
            visual_stage.validate_preserved(script_text, chapters)
    else:
        if script_mode:
            n = visual_stage.scenes_for_script(script_text, cfg)
        else:
            n = scenes_stage.scenes_for_duration(cfg.duration_target)
        try:
            chapters, scenes_source = scenes_stage.build_chapters(
                script_text, cfg, n_scenes=n, metrics=metrics)
        except nvidia_stage.NvidiaError as exc:
            if not script_mode:
                raise
            # Modo roteiro-pronto: sem API, a divisão local basta — ela
            # agrupa frases literais e sempre preserva a narração.
            print(f"AVISO: {exc} — usando divisão local.", file=sys.stderr)
            warnings.append(f"cenas locais (NVIDIA indisponível: {exc})")
            chapters = scenes_stage._local_chapters(script_text, n)
            scenes_source = "local"
        if script_mode:
            visual_stage.validate_preserved(script_text, chapters)
        _write_json(paths.chapters_json, [c.to_dict() for c in chapters])
    stage_times["scenes"] = round(time.monotonic() - t0, 2)
    emit(2, "Interpretando cenas", "OK")

    # [3/6] Mídia
    t0 = time.monotonic()
    emit(3, "Buscando mídia")
    media_scenes = None
    if not force_after_script and os.path.isfile(paths.media_json):
        try:
            saved = _read_json(paths.media_json)
            chapter_ok = ([s["chapter_id"] for s in saved] ==
                          [c.id for c in chapters])
            files_ok = True
            for s in saved:
                first = s.get("asset")
                if first is not None and not os.path.isfile(
                        first.get("local_path", "")):
                    files_ok = False
                    break
                if max_images > 1:
                    if "assets" not in s:
                        files_ok = False
                        break
                    for im in s.get("assets", []):
                        asset = im.get("asset", {})
                        if not os.path.isfile(asset.get("local_path", "")):
                            files_ok = False
                            break
            if chapter_ok and files_ok:
                media_scenes = saved
        except (json.JSONDecodeError, KeyError):
            media_scenes = None
    if media_scenes is None:
        if max_images > 1:
            media_scenes, media_warnings = visual_stage.fetch_media_multi(
                chapters, cfg, max_images, metrics)
        else:
            media_scenes, media_warnings = _fetch_media(chapters, cfg, paths,
                                                       metrics)
        warnings.extend(media_warnings)
        _write_json(paths.media_json, media_scenes)
    stage_times["media"] = round(time.monotonic() - t0, 2)
    emit(3, "Buscando mídia",
         "AVISO" if any(s["asset"] is None for s in media_scenes) else "OK")

    if narration == "human":
        return _human_prep(idea, slug, cfg, paths, script_text, script_source,
                           chapters, scenes_source, media_scenes, warnings,
                           stage_times, started, emit, metrics,
                           script_mode=script_mode, max_images=max_images,
                           overlap_cap=overlap_cap)

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
                                   words_path=paths.words_json, metrics=metrics)
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
    visual_timeline = (_write_visual_timeline(chapters, media_scenes, paths,
                                              slug, overlap_cap,
                                              cfg.visual_sfx)
                       if max_images > 1 else [])

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
    sfx_path = None
    if not force and os.path.isfile(paths.final_mp4):
        video_duration = ff.probe_duration(paths.final_mp4)
        render_info = {"backend": "cache", "encoder": "cache",
                       "duration": video_duration, "path": paths.final_mp4}
        cached_sfx = os.path.join(paths.root, "audio", "sfx.wav")
        if visual_timeline and os.path.isfile(cached_sfx):
            sfx_path = cached_sfx
    else:
        silent = paths.silent_mp4
        if force or not os.path.isfile(silent):
            if visual_timeline:
                _build_silent_visual(chapters, visual_timeline, idea, paths,
                                     cfg, silent)
            else:
                _build_silent(chapters, media_scenes, idea, durations, paths,
                              cfg, silent)
        narration_wav = paths.narration_wav
        sfx_path = (_sfx_track_for(visual_timeline, total, paths)
                    if visual_timeline and cfg.visual_sfx else None)
        if sfx_path:
            narration_wav = _narration_with_sfx(paths.narration_wav, sfx_path,
                                                total, paths)
        render_info = render_stage.burn_final(
            silent, paths.subs_ass, narration_wav, paths.final_mp4,
            cfg, total)
        video_duration = render_info["duration"]
    stage_times["render"] = round(time.monotonic() - t0, 2)
    emit(6, "Montando vídeo", "OK")

    metadata = _base_metadata(idea, slug, cfg, script_text, script_source,
                              chapters, scenes_source, media_scenes, warnings,
                              stage_times, started)
    metadata.update({
        "narration": "ai",
        "mode": "script" if script_mode else "idea",
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
        "visual": ({
            "max_images": max_images,
            "overlap_cap": overlap_cap,
            "sfx": bool(sfx_path),
        } if max_images > 1 else None),
        "artifacts": {
            "script": paths.script_txt,
            "chapters": paths.chapters_json,
            "media": paths.media_json,
            "audio": paths.narration_wav,
            "words": paths.words_json,
            "timeline": paths.timeline_json,
            **({"visual_timeline": paths.visual_json}
               if max_images > 1 else {}),
            **({"sfx": sfx_path} if sfx_path else {}),
            "subtitles": paths.subs_srt,
            "subtitles_ass": paths.subs_ass,
            "silent": paths.silent_mp4,
            "video": paths.final_mp4,
        },
    })
    _write_json(paths.metadata_json, metadata)
    stage_times["finalize"] = 0.0
    metadata["stage_times"] = stage_times
    metadata["metrics_file"] = metrics.save(metadata, stage_times,
                                            cfg.metrics_dir)
    return metadata


def run_script_pipeline(script_text: str, cfg: CurioConfig,
                        title: str | None = None, slug: str | None = None,
                        force: bool = False, narration: str = "ai",
                        max_images: int | None = None,
                        on_progress=None) -> dict:
    """Modo roteiro-pronto: organiza mídia sobre um roteiro já existente.

    O texto é usado verbatim como narração/legenda — nunca gerado nem
    reescrito. `title` vira título/metadados; sem ele, usa-se a primeira
    linha do roteiro. `max_images` (1–5, padrão da config) é o nº de fotos
    por cena com sobreposição em álbum.
    """
    text = (script_text or "").strip()
    if not text:
        raise ValueError("roteiro vazio — nada para produzir")
    if title is None:
        first_line = next((ln.strip() for ln in text.splitlines()
                           if ln.strip()), text[:90])
        title = first_line[:90]
    slug = slug or slugify(title)
    if max_images is None:
        max_images = cfg.visual_max_images
    return run_pipeline(title, cfg, slug=slug, force=force,
                        narration=narration, on_progress=on_progress,
                        provided_script=text, max_images=max_images)


def _human_prep(idea: str, slug: str, cfg: CurioConfig, paths: VideoPaths,
                script_text: str, script_source: str, chapters: list[Chapter],
                scenes_source: str, media_scenes: list[dict],
                warnings: list[str], stage_times: dict, started: float,
                emit, metrics, script_mode: bool = False,
                max_images: int = 1, overlap_cap: float = 0.9) -> dict:
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
    visual_timeline = (_write_visual_timeline(chapters, media_scenes, paths,
                                              slug, overlap_cap,
                                              cfg.visual_sfx)
                       if max_images > 1 else [])
    stage_times["timeline"] = round(time.monotonic() - t0, 2)
    emit(4, "Estimando timeline", "OK")

    # [5/6] Vídeo silencioso
    t0 = time.monotonic()
    emit(5, "Montando silencioso")
    if visual_timeline:
        _build_silent_visual(chapters, visual_timeline, idea, paths, cfg,
                             paths.silent_mp4)
    else:
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
        "mode": "script" if script_mode else "idea",
        "duration_actual": estimated_total,
        "teleprompter_wpm": cfg.teleprompter_wpm,
        "teleprompter_cues": tele_cues,
        "visual": ({
            "max_images": max_images,
            "overlap_cap": overlap_cap,
        } if max_images > 1 else None),
        "artifacts": {
            "script": paths.script_txt,
            "chapters": paths.chapters_json,
            "media": paths.media_json,
            "timeline": paths.timeline_json,
            **({"visual_timeline": paths.visual_json}
               if max_images > 1 else {}),
            "silent": paths.silent_mp4,
            "teleprompter": paths.tele_mp4,
            "teleprompter_ass": paths.tele_ass,
        },
    })
    _write_json(paths.metadata_json, metadata)
    metadata["stage_times"] = stage_times
    metadata["metrics_file"] = metrics.save(metadata, stage_times,
                                            cfg.metrics_dir)
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
                                            cfg.whisper_model, metrics=metrics)
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
    visual_timeline = None
    if os.path.isfile(paths.visual_json):
        try:
            visual_timeline = _read_json(paths.visual_json)
        except json.JSONDecodeError:
            visual_timeline = None
    if abs(diff) <= 0.3:
        pass  # compatível: reusa o silencioso
    elif diff > 0:
        # Áudio mais longo: estende a ÚLTIMA cena (nunca corta a fala).
        adj = os.path.join(paths.root, "render", "silent_adj.mp4")
        if visual_timeline:
            chapters[-1].end = round(chapters[-1].end + diff, 3)
            _write_json(paths.timeline_json,
                        [c.to_dict() for c in chapters])
            visual_timeline = visual_stage.retime_visual_timeline(
                visual_timeline, chapters)
            _write_json(paths.visual_json, visual_timeline)
            _build_silent_visual(chapters, visual_timeline, idea, paths,
                                 cfg, adj)
        else:
            durations = [c.end - c.start for c in chapters]
            durations[-1] += diff
            _build_silent(chapters, media_scenes, idea, durations, paths,
                          cfg, adj)
        silent = adj
        warnings.append(f"última cena estendida +{diff:.1f}s p/ caber o áudio")
    else:
        warnings.append(f"áudio {abs(diff):.1f}s mais curto — cauda cortada")
    emit("Ajustando visual", "OK")

    emit("Merge final")
    total = round(human_dur + 0.5, 2)
    human_wav = paths.human_wav
    sfx_path = None
    if visual_timeline and cfg.visual_sfx:
        sfx_path = _sfx_track_for(visual_timeline, total, paths)
        if sfx_path:
            human_wav = _narration_with_sfx(paths.human_wav, sfx_path,
                                            total, paths)
    render_info = render_stage.burn_final(
        silent, paths.subs_ass, human_wav, paths.final_mp4, cfg, total)
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
    if sfx_path:
        meta["artifacts"]["sfx"] = sfx_path
    _write_json(paths.metadata_json, meta)
    meta["metrics_file"] = metrics.save(meta, {"finalize": round(
        time.monotonic() - started, 2)}, cfg.metrics_dir)
    return meta
