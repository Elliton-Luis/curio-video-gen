import pytest

from curio.config import CurioConfig
from curio.pipeline import run_pipeline
from curio.pipeline_input import PipelineInput


def test_pipeline_input_trims_topic_and_display_title_but_preserves_script():
    request = PipelineInput(
        topic="  Black holes  ", script="  First line\n\n  Second line  ",
        display_title="  Field notes  ")

    assert request.topic == "Black holes"
    assert request.script == "  First line\n\n  Second line  "
    assert request.display_title == "Field notes"


@pytest.mark.parametrize("kwargs", [
    {"topic": "  "},
    {"topic": "Black holes", "script": "\n "},
    {"topic": "Black holes", "display_title": " "},
])
def test_pipeline_input_rejects_empty_required_values(kwargs):
    with pytest.raises(ValueError):
        PipelineInput(**kwargs)


@pytest.mark.parametrize("kwargs", [
    {"topic": 42},
    {"topic": "Black holes", "script": object()},
    {"topic": "Black holes", "display_title": object()},
])
def test_pipeline_input_rejects_non_text_fields(kwargs):
    with pytest.raises(TypeError):
        PipelineInput(**kwargs)


def test_pipeline_input_is_immutable():
    request = PipelineInput(topic="Black holes")

    with pytest.raises(AttributeError):
        request.topic = "History"


def test_pipeline_entrypoint_rejects_untyped_topic():
    with pytest.raises(TypeError, match="requires PipelineInput"):
        run_pipeline("Black holes", CurioConfig())
