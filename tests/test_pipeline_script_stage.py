from curio.config import CurioConfig
from curio.pipeline import video_paths
from curio.pipeline_script import run_script_stage
from curio.stages.script import TitleArtifact
import os


def test_changed_provided_script_explicitly_invalidates_downstream_audio(
        tmp_path, monkeypatch):
    cfg = CurioConfig()
    cfg.out_dir = str(tmp_path)
    paths = video_paths(cfg.out_dir, "project")
    os.makedirs(os.path.dirname(paths.script_txt), exist_ok=True)
    with open(paths.script_txt, "w", encoding="utf-8") as stream:
        stream.write("Narração anterior.")
    monkeypatch.setattr(
        "curio.stages.research.verify_grounding",
        lambda *_args, **_kwargs: {"unverified": [], "checked": 0})
    monkeypatch.setattr(
        "curio.stages.script.generate_title",
        lambda *_args, **_kwargs: TitleArtifact("A pergunta?", "test"))

    result = run_script_stage(
        "ideia", cfg, paths, None, research_prompt="", research_target=None,
        research_sources=[], genre_directive=None, force=False,
        provided_script="Uma narração nova.")

    assert result.script_changed is True
    assert result.force_scenes is True
    assert result.script.text == "Uma narração nova."


def test_cache_autocorrection_invalidates_scene_and_audio_inputs(
        tmp_path, monkeypatch):
    cfg = CurioConfig()
    paths = video_paths(str(tmp_path), "legacy")
    os.makedirs(os.path.dirname(paths.script_txt), exist_ok=True)
    with open(paths.script_txt, "w", encoding="utf-8") as stream:
        stream.write("1) Texto salvo.")
    monkeypatch.setattr(
        "curio.stages.research.verify_grounding",
        lambda *_args, **_kwargs: {"unverified": [], "checked": 0})
    monkeypatch.setattr(
        "curio.stages.script.generate_title",
        lambda *_args, **_kwargs: TitleArtifact("A pergunta?", "test"))

    result = run_script_stage(
        "ideia", cfg, paths, None, research_prompt="", research_target=None,
        research_sources=[], genre_directive=None, force=False)

    assert result.script.source == "cache"
    assert result.script.text == "Texto salvo."
    assert result.script_changed is True
    assert result.force_scenes is True
