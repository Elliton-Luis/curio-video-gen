"""Input handling and literal-scene rules for user-provided scripts."""

from __future__ import annotations

import os

from ..config import CurioConfig
from . import editorial as editorial_stage
from . import scenes as scenes_stage


def read_script_file(path: str) -> str:
    """Read supplied narration without rewriting its words or order."""
    if path == "-":
        import sys
        text = sys.stdin.read()
    else:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"roteiro não encontrado: {path}")
        with open(path, encoding="utf-8-sig") as stream:
            text = stream.read()
    text = text.strip()
    if not text:
        raise ValueError("roteiro vazio — informe um texto para narrar")
    return text


def scenes_for_script(script_text: str, cfg: CurioConfig,
                      genre: str = "") -> int:
    """Choose enough scenes for the literal script under genre pacing."""
    profile = editorial_stage.get(genre)
    pacing = profile.pacing if profile is not None else None
    target_seconds = pacing.target_scene_seconds if pacing is not None else 9.0
    max_scenes = pacing.max_scenes if pacing is not None else None
    by_length = scenes_stage.scenes_for_length(
        len(script_text.split()), target_seconds, max_scenes)
    if cfg.duration_target <= 0:
        return by_length
    return max(scenes_stage.scenes_for_duration(
        cfg.duration_target, target_seconds, max_scenes), by_length)


def validate_preserved(original: str, scenes) -> None:
    """Reject scene splits that changed the supplied narration."""
    joined = " ".join(scene.narration for scene in scenes)
    if scenes_stage._norm(joined) != scenes_stage._norm(original):
        raise ValueError(
            "divisão em cenas não reproduz o roteiro literal — "
            "recusando para não adulterar a narração")
