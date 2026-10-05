"""Preparação de segmentos e política de transições do pipeline."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from .config import CurioConfig
from .media.selection_result import MediaStageResult
from .stages import editorial as editorial_stage
from .stages import render as render_stage
from .stages.scene_contract import SemanticScene, TimelineSpan


@dataclass(frozen=True)
class RenderAsset:
    """Minimal media input needed to render one scene."""

    local_path: str
    kind: str
    identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.local_path, str) or not isinstance(self.kind, str):
            raise TypeError("render asset path and kind must be strings")
        if not isinstance(self.identity, str):
            raise TypeError("render asset identity must be a string")

    @classmethod
    def from_media_dict(cls, value: object) -> "RenderAsset":
        if not isinstance(value, dict):
            raise TypeError("render asset must be an object")
        local_path = value.get("local_path", "") or ""
        kind = value.get("kind", "image") or "image"
        if not isinstance(local_path, str) or not isinstance(kind, str):
            raise TypeError("render asset path and kind must be strings")
        identity = json.dumps(value, sort_keys=True, ensure_ascii=False)
        return cls(local_path, kind, identity)


@dataclass(frozen=True)
class SceneRenderInput:
    scene_id: int
    asset: RenderAsset | None

    def __post_init__(self) -> None:
        if isinstance(self.scene_id, bool) or not isinstance(self.scene_id, int) \
                or self.scene_id <= 0:
            raise ValueError("render scene id must be a positive integer")
        if self.asset is not None and not isinstance(self.asset, RenderAsset):
            raise TypeError("render scene asset must be RenderAsset or null")


@dataclass(frozen=True)
class SceneRenderPlan:
    scenes: tuple[SceneRenderInput, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.scenes, tuple):
            raise TypeError("render plan scenes must be a tuple")
        if any(not isinstance(scene, SceneRenderInput) for scene in self.scenes):
            raise TypeError("render plan requires SceneRenderInput values")
        ids = tuple(scene.scene_id for scene in self.scenes)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("render plan requires unique positive scene ids")

    @classmethod
    def from_media_result(cls, result: MediaStageResult) -> "SceneRenderPlan":
        if not isinstance(result, MediaStageResult):
            raise TypeError("render plan requires a MediaStageResult")
        return cls(tuple(SceneRenderInput(
            scene.scene_id,
            RenderAsset.from_media_dict(scene.asset.to_dict())
            if scene.asset is not None else None)
            for scene in result.scenes))

    @classmethod
    def from_persisted_rows(cls, rows: object) -> "SceneRenderPlan":
        """Read the project media format without inventing editorial identity."""
        if not isinstance(rows, list):
            raise TypeError("persisted media must be a list")
        scenes = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("persisted media scene must be an object")
            scene_id = row.get("chapter_id")
            if isinstance(scene_id, bool) or not isinstance(scene_id, int):
                raise ValueError("persisted media chapter_id must be an integer")
            asset = row.get("asset")
            if asset is not None and not isinstance(asset, dict):
                raise TypeError("persisted media asset must be an object or null")
            scenes.append(SceneRenderInput(
                scene_id, RenderAsset.from_media_dict(asset) if asset else None))
        return cls(tuple(scenes))

    def for_scenes(self, scenes: tuple[SemanticScene, ...]) -> dict[int, RenderAsset | None]:
        expected = tuple(scene.id for scene in scenes)
        actual = tuple(scene.scene_id for scene in self.scenes)
        if expected != actual:
            raise ValueError("render plan scenes do not match semantic scene order")
        return {scene.scene_id: scene.asset for scene in self.scenes}


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


def _segment_identity(assets: list[RenderAsset], cfg: CurioConfig,
                      variant: int) -> str:
    """Invalidate segment cache when assets, file contents or presentation change."""
    files = []
    for asset in assets:
        path = asset.local_path if asset else ""
        if path and os.path.isfile(path):
            stat = os.stat(path)
            files.append((path, stat.st_size, stat.st_mtime_ns))
    payload = [[asset.identity for asset in assets], files,
               cfg.width, cfg.height, cfg.fps,
               cfg.render_backend, variant]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _scene_segment(scene_id: int, asset: RenderAsset | None, idea: str,
                   duration: float, paths, cfg: CurioConfig,
                   variant: int) -> str:
    identity = _segment_identity([asset] if asset else [], cfg, variant)
    segment = os.path.join(paths.root, "render", "segments",
                           f"scene{scene_id}_{identity}_{duration:.1f}s.mp4")
    if os.path.isfile(segment):
        return segment
    os.makedirs(os.path.dirname(segment), exist_ok=True)
    if asset and asset.local_path:
        local = asset.local_path
        if asset.kind == "video":
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
    render_assets = [RenderAsset.from_media_dict(image)
                     for image in (*images, *backgrounds)]
    identity = _segment_identity(render_assets, cfg, variant)
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
        RenderAsset.from_media_dict(
            {"local_path": asset["local_path"],
             "kind": asset.get("kind", "image")})
        if asset else None,
        idea, duration, paths, cfg, variant)


def build_silent(semantic_scenes: tuple[SemanticScene, ...],
                 timeline_spans: tuple[TimelineSpan, ...],
                 render_plan: SceneRenderPlan, idea: str,
                 paths, cfg: CurioConfig, out_path: str,
                 transitions: list[float] | None = None,
                 kinds: list[str] | None = None) -> str:
    _validate_render_inputs(semantic_scenes, timeline_spans)
    if not isinstance(render_plan, SceneRenderPlan):
        raise TypeError("silent render requires a SceneRenderPlan")
    assets = render_plan.for_scenes(semantic_scenes)
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
