"""Explicit Chapter adapter for tests of the semantic visual timeline API."""


def build_visual_timeline(timeline_stage, chapters, media_scenes, *args, **kwargs):
    scenes = tuple(chapter.semantic_scene("test_fixture") for chapter in chapters)
    spans = tuple(chapter.timeline_span() for chapter in chapters)
    return timeline_stage.build_visual_timeline(
        scenes, spans, media_scenes, *args, **kwargs)
