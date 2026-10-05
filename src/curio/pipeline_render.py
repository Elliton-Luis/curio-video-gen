"""Preparação de segmentos e política de transições do pipeline."""

from __future__ import annotations

import hashlib
import json
import os

from .config import CurioConfig
from .stages import editorial as editorial_stage
from .stages import render as render_stage
from .stages.scene_contract import SemanticScene, TimelineSpan


def title_fontfile(cfg: CurioConfig, genre_key: str = "") -> str | None:
    """Resolve the burned-title font, falling back to the display font."""
    from .stages import subs as subs_stage
    from .stages import typography as typo_stage
    if not genre_key:
        return subs_stage.ensure_display_font(cfg.cache_dir)[2]
    resolved = typo_stage.resolve(typo_stage.ROLE_TITLE, genre_key,
                                  (cfg.typography or {}).get(genre_key))
    if resolved.path:
        return resolved.path
    return subs_stage.ensure_display_font(cfg.cache_dir)[2]


def _segment_identity(assets: list, cfg: CurioConfig, variant: int) -> str:
    """Invalidate segment cache when assets, file contents or presentation change."""
    files = []
    for asset in assets:
        path = (asset or {}).get("local_path")
        if path and os.path.isfile(path):
            stat = os.stat(path)
            files.append((path, stat.st_size, stat.st_mtime_ns))
    payload = [assets, files, cfg.width, cfg.height, cfg.fps,
               cfg.render_backend, variant]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _scene_segment(scene_id: int, asset_dict: dict | None, idea: str,
                   duration: float, paths, cfg: CurioConfig,
                   variant: int) -> str:
    identity = _segment_identity([asset_dict] if asset_dict else [], cfg, variant)
    segment = os.path.join(paths.root, "render", "segments",
                           f"scene{scene_id}_{identity}_{duration:.1f}s.mp4")
    if os.path.isfile(segment):
        return segment
    os.makedirs(os.path.dirname(segment), exist_ok=True)
    if asset_dict and asset_dict.get("local_path"):
        local = asset_dict["local_path"]
        if asset_dict.get("kind") == "video":
            return render_stage.render_video_segment(local, duration, segment, cfg)
        if os.path.isfile(local):
            return render_stage.render_image_segment(local, duration, segment,
                                                     cfg, variant)
    return render_stage.render_fallback_segment(
        duration, segment, cfg, render_stage._wrap_title(idea))


def _visual_segment(trecho: dict, idea: str, duration: float,
                    paths, cfg: CurioConfig, variant: int) -> str:
    """Build one from-script segment: collage for multiple selected images."""
    images = [dict(img) for img in trecho.get("images", [])
              if img.get("local_path") and os.path.isfile(img["local_path"])]
    backgrounds = [dict(img) for img in trecho.get("backgrounds", [])
                   if img.get("local_path") and os.path.isfile(img["local_path"])]
    identity = _segment_identity([*images, *backgrounds], cfg, variant)
    segment = os.path.join(paths.root, "render", "segments",
                           f"scene{trecho['chapter_id']}_visual_{identity}_{duration:.1f}s.mp4")
    if os.path.isfile(segment):
        return segment
    os.makedirs(os.path.dirname(segment), exist_ok=True)
    if len(backgrounds) >= 2 or len(images) >= 2:
        return render_stage.render_collage_segment(
            images, duration, segment, cfg, variant, backgrounds=backgrounds)
    asset = backgrounds[0] if backgrounds else images[0] if images else None
    return _scene_segment(
        int(trecho["chapter_id"]),
        {"local_path": asset["local_path"], "kind": asset.get("kind", "image")}
        if asset else None,
        idea, duration, paths, cfg, variant)


def build_silent(semantic_scenes: tuple[SemanticScene, ...],
                 timeline_spans: tuple[TimelineSpan, ...],
                 media_scenes: list[dict], idea: str,
                 paths, cfg: CurioConfig, out_path: str,
                 transitions: list[float] | None = None,
                 kinds: list[str] | None = None) -> str:
    _validate_render_inputs(semantic_scenes, timeline_spans)
    assets = {scene["chapter_id"]: scene["asset"] for scene in media_scenes}
    segments = [_scene_segment(scene.id, assets.get(scene.id), idea,
                               round(max(0.5, span.end - span.start), 1),
                               paths, cfg, variant=index)
                for index, (scene, span) in enumerate(
                    zip(semantic_scenes, timeline_spans))]
    return (render_stage.concat_with_transitions(segments, out_path, cfg,
                                                transitions, kinds)
            if transitions else render_stage.concat_copy(segments, out_path, cfg))


def build_silent_visual(semantic_scenes: tuple[SemanticScene, ...],
                        timeline_spans: tuple[TimelineSpan, ...],
                        visual_timeline: list[dict],
                        idea: str, paths, cfg: CurioConfig, out_path: str,
                        transitions: list[float] | None = None,
                        kinds: list[str] | None = None) -> str:
    _validate_render_inputs(semantic_scenes, timeline_spans)
    scenes = {scene["chapter_id"]: scene for scene in visual_timeline}
    segments = []
    for index, (semantic_scene, span) in enumerate(
            zip(semantic_scenes, timeline_spans)):
        scene = scenes.get(semantic_scene.id, {})
        duration = round(max(0.5, span.end - span.start), 1)
        trecho = ({"chapter_id": semantic_scene.id, "narration": semantic_scene.narration,
                   "images": scene.get("images", []),
                   "backgrounds": scene.get("backgrounds", [])}
                  if scene else
                  {"chapter_id": semantic_scene.id, "narration": semantic_scene.narration,
                   "images": []})
        segments.append(_visual_segment(trecho, idea, duration, paths, cfg, index))
    return (render_stage.concat_with_transitions(segments, out_path, cfg,
                                                transitions, kinds)
            if transitions else render_stage.concat_copy(segments, out_path, cfg))


def genre_transitions(semantic_scenes: tuple[SemanticScene, ...], genre: str,
                      mode: str = "auto") -> list[float]:
    """Cross-dissolve from adapter; dramatic scene boundaries stay cuts."""
    if mode == "none" or len(semantic_scenes) < 2:
        return [0.0] * max(0, len(semantic_scenes) - 1)
    adapter = editorial_stage.get(genre)
    base = adapter.transition_duration if adapter else 0.20
    result = []
    for scene in semantic_scenes[1:]:
        text = (scene.narration or "").lower()
        if any(term in text for term in ("morreu", "invadiu", "destruiu",
                                         "assassinado", "eclodiu", "de repente")):
            duration = 0.04
        elif any(term in text for term in ("na verdade", "descobriu", "revelou",
                                           "pela primeira vez", "mas foi")):
            duration = min(0.55, base + 0.18)
        elif scene.text_role == "quote" or scene.visual_type in (
                "typographic", "historical_art"):
            duration = min(0.55, base + 0.12)
        else:
            duration = base
        result.append(duration)
    return result


def genre_transition_kinds(semantic_scenes: tuple[SemanticScene, ...], genre: str,
                           mode: str = "auto") -> list[str]:
    if mode == "none" or len(semantic_scenes) < 2:
        return ["fade"] * max(0, len(semantic_scenes) - 1)
    adapter = editorial_stage.get(genre)
    kind = adapter.transition_kind if adapter else "fade"
    return [kind] * (len(semantic_scenes) - 1)


def transition_signature(semantic_scenes: tuple[SemanticScene, ...],
                         timeline_spans: tuple[TimelineSpan, ...],
                         genre: str, mode: str,
                         visual_identity: dict | None = None) -> str:
    _validate_render_inputs(semantic_scenes, timeline_spans)
    transitions = genre_transitions(semantic_scenes, genre, mode)
    kinds = genre_transition_kinds(semantic_scenes, genre, mode)
    payload = {"genre": genre, "mode": mode, "durations": transitions,
               "kinds": kinds, "visual_identity": visual_identity or {},
               "scenes": [(scene.id, scene.visual_type, scene.text_role,
                           span.start, span.end)
                          for scene, span in zip(semantic_scenes, timeline_spans)]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def final_cache_is_current(*, output_exists: bool, force: bool,
                           subtitles_changed: bool, transition_dirty: bool,
                           narration_reused: bool,
                           audio_cache_matches: bool) -> bool:
    """Reuse final MP4 only when every embedded artifact remains current."""
    return bool(output_exists and not force and not subtitles_changed
                and not transition_dirty and narration_reused
                and audio_cache_matches)


def _validate_render_inputs(semantic_scenes, timeline_spans) -> None:
    if (any(not isinstance(scene, SemanticScene) for scene in semantic_scenes)
            or any(not isinstance(span, TimelineSpan) for span in timeline_spans)):
        raise TypeError("render requires SemanticScene and TimelineSpan values")
    scene_ids = tuple(scene.id for scene in semantic_scenes)
    span_ids = tuple(span.scene_id for span in timeline_spans)
    if (not scene_ids or len(scene_ids) != len(set(scene_ids))
            or scene_ids != span_ids):
        raise ValueError("render scenes and spans are misaligned")
