"""Pure audio-word alignment for semantic scenes and timeline spans."""

from __future__ import annotations

import re
from dataclasses import replace

from .scene_contract import SemanticScene, TimelineSpan


def align_word_boundaries(scenes: tuple[SemanticScene, ...],
                          spans: tuple[TimelineSpan, ...],
                          words: list[dict]) -> tuple[TimelineSpan, ...]:
    """Align each narration span to its corresponding TTS word boundaries."""
    _validate_alignment(scenes, spans)
    script_words = [_norm(word) for scene in scenes
                    for word in scene.narration.split()]
    boundary_words = [_norm(str(word.get("text", ""))) for word in words]
    boundary_words = [word for word in boundary_words if word]
    if len(script_words) != len(boundary_words):
        raise ValueError(
            f"contagem de palavras diverge (roteiro={len(script_words)}, "
            f"áudio={len(boundary_words)})")
    result = []
    index = 0
    for scene, span in zip(scenes, spans):
        count = len(scene.narration.split())
        scene_words = words[index:index + count]
        result.append(TimelineSpan(
            scene_id=scene.id, duration_estimate=span.duration_estimate,
            start=float(scene_words[0]["start"]),
            end=float(scene_words[-1]["end"])))
        index += count
    return _close_timeline(tuple(result),
                           float(words[-1]["end"]) if words else 0.0)


def proportional_spans(scenes: tuple[SemanticScene, ...],
                       spans: tuple[TimelineSpan, ...], audio_duration: float,
                       start: float = 0.15) -> tuple[TimelineSpan, ...]:
    """Distribute audio by narration length when word boundaries are invalid."""
    _validate_alignment(scenes, spans)
    total_words = sum(len(scene.narration.split()) for scene in scenes) or 1
    cursor = start
    result = []
    for scene, span in zip(scenes, spans):
        share = audio_duration * len(scene.narration.split()) / total_words
        result.append(TimelineSpan(scene.id, span.duration_estimate,
                                   cursor, cursor + share))
        cursor += share
    return _close_timeline(tuple(result), audio_duration)


def _close_timeline(spans: tuple[TimelineSpan, ...],
                    audio_duration: float) -> tuple[TimelineSpan, ...]:
    if not spans:
        return spans
    result = list(spans)
    result[0] = replace(result[0], start=0.0)
    for index in range(len(result) - 1):
        midpoint = round((result[index].end + result[index + 1].start) / 2, 3)
        result[index] = replace(result[index], end=midpoint)
        result[index + 1] = replace(result[index + 1], start=midpoint)
    result[-1] = replace(result[-1], end=round(audio_duration, 3))
    return tuple(result)


def _validate_alignment(scenes, spans) -> None:
    scene_ids = tuple(scene.id for scene in scenes)
    span_ids = tuple(span.scene_id for span in spans)
    if not scenes or scene_ids != span_ids:
        raise ValueError("timing scenes and spans do not match")


def _norm(value: str) -> str:
    return re.sub(r"[^\w\s]", "", re.sub(r"\s+", " ", value.lower()).strip())
