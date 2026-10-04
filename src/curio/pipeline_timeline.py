"""Materialize a visual timeline from selected media and measured scene times."""

from __future__ import annotations

from dataclasses import dataclass

from .stages import visual as visual_stage
from .stages.scene_contract import SemanticScene, TimelineSpan
from .stages.visual_beats import BEAT_SECONDS


@dataclass(frozen=True)
class VisualTimelineResult:
    entries: list[dict]
    insertion_count: int
    enabled: bool


def build_visual_timeline(semantic_scenes: tuple[SemanticScene, ...],
                          timeline_spans: tuple[TimelineSpan, ...],
                          media_scenes: list[dict], paths, slug: str,
                          overlap_cap: float, sfx: bool, insertions: int,
                          insert_style: str, insert_gain_db: int,
                          enabled: bool, metrics, write_json) -> VisualTimelineResult:
    """Build/persist the optional overlay plan and update its metric projection."""
    scene_ids = tuple(scene.id for scene in semantic_scenes)
    span_ids = tuple(span.scene_id for span in timeline_spans)
    if enabled and (not scene_ids or len(scene_ids) != len(set(scene_ids))
                    or scene_ids != span_ids):
        raise ValueError("visual timeline scenes and spans are misaligned")
    entries = []
    if enabled:
        entries = visual_stage.build_visual_timeline(
            semantic_scenes, timeline_spans, media_scenes,
            overlap_cap, seed=slug, sfx=sfx,
            insertions=insertions, insert_style=insert_style,
            insert_gain_db=insert_gain_db)
        write_json(paths.visual_json, entries)
        from .stages import visual_timeline as visual_timeline_stage
        print(f"Timeline visual: {visual_timeline_stage.visual_summary(entries)}")
        count = _count_insertions(entries)
        if entries:
            print(f"Inserções: {count} foto(s) complementar(es) caindo sobre o fundo "
                  f"(estilo {insert_style}).")
    else:
        count = 0
    metrics.visual_plan(timeline_spans, media_scenes, BEAT_SECONDS, entries)
    return VisualTimelineResult(entries, count, enabled)


def _count_insertions(entries: list[dict]) -> int:
    return sum(1 for timeline in entries for image in timeline.get("images", [])
               if image.get("order", 0) > 0)
