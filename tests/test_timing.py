import pytest

from curio.stages.scene_contract import (SemanticScene, TimelineSpan,
                                         VisualRepresentation)
from curio.stages.timing import align_word_boundaries, proportional_spans


def test_word_alignment_returns_spans_without_mutating_semantic_scene():
    scene = SemanticScene(id=1, narration="um dois tres",
                          representations=(VisualRepresentation(
                              "visual representation", source="test_fixture"),))
    original = scene.to_dict()
    result = align_word_boundaries(
        (scene,), (TimelineSpan(1, duration_estimate=2.0),),
        [{"text": word, "start": index * 0.5, "end": (index + 1) * 0.5}
         for index, word in enumerate(("um", "dois", "tres"))])

    assert result == (TimelineSpan(1, 2.0, 0.0, 1.5),)
    assert scene.to_dict() == original
    assert not hasattr(scene, "start")


def test_word_alignment_rejects_narration_and_audio_word_count_mismatch():
    scene = SemanticScene(id=1, narration="um dois")
    with pytest.raises(ValueError, match="contagem de palavras diverge"):
        align_word_boundaries((scene,), (TimelineSpan(1, 2),),
                              [{"text": "um", "start": 0, "end": 1}])


def test_proportional_timing_returns_aligned_spans():
    scenes = (SemanticScene(1, "um"), SemanticScene(2, "dois tres"))
    spans = (TimelineSpan(1, 1.0), TimelineSpan(2, 2.0))
    result = proportional_spans(scenes, spans, audio_duration=9.0)

    assert tuple(span.scene_id for span in result) == (1, 2)
    assert result[0].start == 0.0
    assert result[-1].end == 9.0
    assert result[0].end == result[1].start


def test_alignment_rejects_wrong_scene_span_ids():
    with pytest.raises(ValueError, match="do not match"):
        align_word_boundaries((SemanticScene(1, "um"),),
                              (TimelineSpan(2, 1),),
                              [{"text": "um", "start": 0, "end": 1}])
