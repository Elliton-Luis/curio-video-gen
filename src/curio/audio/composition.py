"""Project-level audio composition policy and rendering helpers."""

from __future__ import annotations

import json
import os
import sys

from . import selection as audio_selection
from ..config import CurioConfig
from ..project_paths import VideoPaths
from ..stages import render as render_stage


def sfx_events(visual_timeline: list[dict]) -> list[dict]:
    return [img["sfx"] for entry in visual_timeline
            for img in entry.get("images", [])
            if isinstance(img.get("sfx"), dict)]


def sfx_track(visual_timeline: list[dict], total: float,
              paths: VideoPaths) -> str | None:
    """Build audio/sfx.wav for timeline events, or return None."""
    events = sfx_events(visual_timeline)
    if not events:
        return None
    out = os.path.join(paths.root, "audio", "sfx.wav")
    return render_stage.build_sfx_track(events, total, out)


def narration_with_sfx(wav_path: str, sfx_path: str | None, total: float,
                       paths: VideoPaths) -> str:
    """Mix SFX into narration without changing its volume."""
    if not sfx_path:
        return wav_path
    out = os.path.join(paths.root, "audio", "mixed.wav")
    return render_stage.mix_sfx(wav_path, sfx_path, out, total)


def final_audio_fade(genre: str, transitions: str = "auto") -> float:
    if transitions == "none" or not genre:
        return 0.0
    return {"people": 0.8, "history": 0.65, "etymology": 0.35,
            "mythology": 0.75, "mystery": 0.7, "science": 0.3}.get(genre, 0.0)


def transition_mode(cfg: CurioConfig) -> str:
    """Audio absent in old projects preserves cuts and legacy render."""
    active = bool(getattr(cfg, "audio_enabled", False)) or cfg.music_mode != "auto"
    return cfg.music_transitions if active else "none"


def mark_audio_used(cfg: CurioConfig, plan: dict) -> None:
    try:
        audio_selection.mark_used(
            cfg.audio_library_dir, plan.get("music_asset"),
            plan.get("sfx_assets") or [])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"AVISO: não foi possível atualizar uso da biblioteca de áudio: {exc}",
              file=sys.stderr)


def apply_audio_request(cfg: CurioConfig, audio: dict | None) -> None:
    """Apply a project's persisted audio choice to its run-local config."""
    if not isinstance(audio, dict):
        return
    cfg.audio_enabled = True
    music = audio.get("music") if isinstance(audio.get("music"), dict) else {}
    if music.get("mode") in ("auto", "none", "manual"):
        cfg.music_mode = music["mode"]
    if music.get("gain_db") is not None:
        cfg.music_gain_db = max(-40, min(-3, int(music["gain_db"])))
    if music.get("ducking") is not None:
        cfg.music_ducking = bool(music["ducking"])
    track = music.get("track") if isinstance(music.get("track"), dict) else {}
    if cfg.music_mode == "manual" and track.get("path"):
        cfg.music_file = str(track["path"])
    transitions = audio.get("transitions")
    if isinstance(transitions, dict) and transitions.get("mode") in ("auto", "none"):
        cfg.music_transitions = transitions["mode"]
