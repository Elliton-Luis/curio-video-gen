from curio.config import CurioConfig
from curio.pipeline import video_paths
from curio.pipeline_script import run_script_stage
from curio.script_artifacts import (ScriptArtifactsManifest, read_manifest,
                                    text_identity, write_manifest)
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


def test_external_script_edit_is_preserved_and_invalidates_derived_artifacts(
        tmp_path, monkeypatch):
    cfg = CurioConfig()
    paths = video_paths(str(tmp_path), "edited-script")
    os.makedirs(os.path.dirname(paths.script_txt), exist_ok=True)
    os.makedirs(os.path.dirname(paths.title_txt), exist_ok=True)
    old_script, edited_script = "Texto antigo.", "Texto editado pelo usuário."
    old_title = "Título anterior?"
    with open(paths.script_txt, "w", encoding="utf-8") as stream:
        stream.write(edited_script)
    with open(paths.title_txt, "w", encoding="utf-8") as stream:
        stream.write(old_title)
    write_manifest(paths.script_manifest_json, ScriptArtifactsManifest(
        script_sha256=text_identity(old_script), script_origin="template",
        title_sha256=text_identity(old_title), title_origin="generated",
        title_script_sha256=text_identity(old_script)))
    monkeypatch.setattr(
        "curio.stages.research.verify_grounding",
        lambda *_args, **_kwargs: {"unverified": [], "checked": 0})
    monkeypatch.setattr(
        "curio.stages.script.generate_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an edited project script is authoritative")))
    monkeypatch.setattr(
        "curio.stages.script.generate_title",
        lambda *_args, **_kwargs: TitleArtifact("Título atualizado?", "test"))

    result = run_script_stage(
        "ideia", cfg, paths, None, research_prompt="", research_target=None,
        research_sources=[], genre_directive=None, force=False)

    assert result.script.text == edited_script
    assert result.script.source == "edited"
    assert result.script_changed is True and result.force_scenes is True
    assert result.title.text == "Título atualizado?"
    assert read_manifest(paths.script_manifest_json).script_origin == "edited"


def test_external_title_edit_is_preserved_as_project_state(tmp_path, monkeypatch):
    cfg = CurioConfig()
    paths = video_paths(str(tmp_path), "edited-title")
    os.makedirs(os.path.dirname(paths.script_txt), exist_ok=True)
    with open(paths.script_txt, "w", encoding="utf-8") as stream:
        stream.write("Stable script.")
    with open(paths.title_txt, "w", encoding="utf-8") as stream:
        stream.write("New title by editor?")
    write_manifest(paths.script_manifest_json, ScriptArtifactsManifest(
        script_sha256=text_identity("Stable script."), script_origin="template",
        title_sha256=text_identity("Generated old title?"),
        title_origin="generated",
        title_script_sha256=text_identity("Stable script.")))
    monkeypatch.setattr(
        "curio.stages.research.verify_grounding",
        lambda *_args, **_kwargs: {"unverified": [], "checked": 0})
    monkeypatch.setattr(
        "curio.stages.script.generate_title",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an edited project title is authoritative")))

    result = run_script_stage(
        "ideia", cfg, paths, None, research_prompt="", research_target=None,
        research_sources=[], genre_directive=None, force=False)

    assert result.script_changed is False
    assert result.title.text == "New title by editor?"
    assert result.title.source == "edited"
    manifest = read_manifest(paths.script_manifest_json)
    assert manifest.title_origin == "edited"
    assert manifest.title_script_sha256 is None
