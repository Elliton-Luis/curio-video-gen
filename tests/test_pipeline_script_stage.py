import json
import os

from curio.config import CurioConfig
from curio.project_paths import video_paths
from curio.pipeline_script import (_script_input_hash, _title_input_hash,
                                   run_script_stage)
from curio.script_artifacts import (ScriptArtifactsManifest, read_manifest,
                                    text_identity, write_manifest)
from curio.stages.script import ScriptArtifact, TitleArtifact


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
        title_script_sha256=text_identity("Stable script."),
        script_input_sha256=_script_input_hash(
            "ideia", cfg, "", None, [], None),
        title_input_sha256=_title_input_hash("Stable script.", "ideia", cfg)))
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


def test_generated_script_cache_invalidates_when_research_inputs_change(
        tmp_path, monkeypatch):
    cfg = CurioConfig()
    paths = video_paths(str(tmp_path), "research-change")
    os.makedirs(os.path.dirname(paths.script_txt), exist_ok=True)
    old_script, new_script = "Old grounded script.", "New grounded script."
    old_title = "Old generated title?"
    with open(paths.script_txt, "w", encoding="utf-8") as stream:
        stream.write(old_script)
    with open(paths.title_txt, "w", encoding="utf-8") as stream:
        stream.write(old_title)
    write_manifest(paths.script_manifest_json, ScriptArtifactsManifest(
        script_sha256=text_identity(old_script), script_origin="template",
        title_sha256=text_identity(old_title), title_origin="generated",
        title_script_sha256=text_identity(old_script),
        script_input_sha256=_script_input_hash(
            "idea", cfg, "old research", None, [], None),
        title_input_sha256=_title_input_hash(old_script, "idea", cfg)))
    monkeypatch.setattr(
        "curio.stages.research.verify_grounding",
        lambda *_args, **_kwargs: {"unverified": [], "checked": 0})
    generated = []
    monkeypatch.setattr(
        "curio.stages.script.generate_script",
        lambda *_args, **_kwargs: (generated.append(True)
                                   or ScriptArtifact(new_script, "template")))
    monkeypatch.setattr(
        "curio.stages.script.generate_title",
        lambda *_args, **_kwargs: TitleArtifact("New generated title?", "test"))

    result = run_script_stage(
        "idea", cfg, paths, None, research_prompt="new research",
        research_target=None, research_sources=[], genre_directive=None,
        force=False)

    assert generated == [True]
    assert result.script.text == new_script
    assert result.force_scenes is True
    manifest = read_manifest(paths.script_manifest_json)
    assert manifest.script_input_sha256 == _script_input_hash(
        "idea", cfg, "new research", None, [], None)


def test_generated_title_cache_requires_current_script_and_inputs(
        tmp_path, monkeypatch):
    cfg = CurioConfig()
    paths = video_paths(str(tmp_path), "title-dependency")
    os.makedirs(os.path.dirname(paths.script_txt), exist_ok=True)
    script, stale_title = "Stable script.", "Stale generated title?"
    with open(paths.script_txt, "w", encoding="utf-8") as stream:
        stream.write(script)
    with open(paths.title_txt, "w", encoding="utf-8") as stream:
        stream.write(stale_title)
    write_manifest(paths.script_manifest_json, ScriptArtifactsManifest(
        script_sha256=text_identity(script), script_origin="template",
        title_sha256=text_identity(stale_title), title_origin="generated",
        title_script_sha256=text_identity("older script"),
        script_input_sha256=_script_input_hash("idea", cfg, "research", None, [], None),
        title_input_sha256=_title_input_hash(script, "idea", cfg)))
    monkeypatch.setattr(
        "curio.stages.research.verify_grounding",
        lambda *_args, **_kwargs: {"unverified": [], "checked": 0})
    monkeypatch.setattr(
        "curio.stages.script.generate_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("valid script cache should be reused")))
    monkeypatch.setattr(
        "curio.stages.script.generate_title",
        lambda *_args, **_kwargs: TitleArtifact("Fresh generated title?", "test"))

    result = run_script_stage(
        "idea", cfg, paths, None, research_prompt="research",
        research_target=None, research_sources=[], genre_directive=None,
        force=False)

    assert result.script.source == "cache"
    assert result.title.text == "Fresh generated title?"


def test_matching_generated_inputs_reuse_both_script_and_title(
        tmp_path, monkeypatch):
    cfg = CurioConfig()
    paths = video_paths(str(tmp_path), "matching-cache")
    os.makedirs(os.path.dirname(paths.script_txt), exist_ok=True)
    script, title = "Stable generated script.", "Stable generated title?"
    with open(paths.script_txt, "w", encoding="utf-8") as stream:
        stream.write(script)
    with open(paths.title_txt, "w", encoding="utf-8") as stream:
        stream.write(title)
    write_manifest(paths.script_manifest_json, ScriptArtifactsManifest(
        script_sha256=text_identity(script), script_origin="template",
        title_sha256=text_identity(title), title_origin="generated",
        title_script_sha256=text_identity(script),
        script_input_sha256=_script_input_hash("idea", cfg, "research", None, [], None),
        title_input_sha256=_title_input_hash(script, "idea", cfg)))
    monkeypatch.setattr(
        "curio.stages.research.verify_grounding",
        lambda *_args, **_kwargs: {"unverified": [], "checked": 0})
    monkeypatch.setattr(
        "curio.stages.script.generate_script",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("matching script inputs must use cache")))
    monkeypatch.setattr(
        "curio.stages.script.generate_title",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("matching title inputs must use cache")))

    result = run_script_stage(
        "idea", cfg, paths, None, research_prompt="research",
        research_target=None, research_sources=[], genre_directive=None,
        force=False)

    assert result.script.source == "cache"
    assert result.title.source == "cache"
    assert result.script_changed is False
    assert result.force_scenes is False


def test_generated_v1_cache_without_input_signature_is_regenerated(
        tmp_path, monkeypatch):
    cfg = CurioConfig()
    paths = video_paths(str(tmp_path), "v1-generated-cache")
    os.makedirs(os.path.dirname(paths.script_txt), exist_ok=True)
    old_script, new_script = "Old generated script.", "Regenerated script."
    old_title = "Old generated title?"
    with open(paths.script_txt, "w", encoding="utf-8") as stream:
        stream.write(old_script)
    with open(paths.title_txt, "w", encoding="utf-8") as stream:
        stream.write(old_title)
    with open(paths.script_manifest_json, "w", encoding="utf-8") as stream:
        json.dump({
            "schema_version": 1,
            "script": {"sha256": text_identity(old_script), "origin": "template"},
            "title": {"sha256": text_identity(old_title), "origin": "generated",
                      "script_sha256": text_identity(old_script)},
        }, stream)
    monkeypatch.setattr(
        "curio.stages.research.verify_grounding",
        lambda *_args, **_kwargs: {"unverified": [], "checked": 0})
    monkeypatch.setattr(
        "curio.stages.script.generate_script",
        lambda *_args, **_kwargs: ScriptArtifact(new_script, "template"))
    monkeypatch.setattr(
        "curio.stages.script.generate_title",
        lambda *_args, **_kwargs: TitleArtifact("Regenerated title?", "test"))

    result = run_script_stage(
        "idea", cfg, paths, None, research_prompt="current research",
        research_target=None, research_sources=[], genre_directive=None,
        force=False)

    assert result.script.text == new_script
    assert result.force_scenes is True
    manifest = read_manifest(paths.script_manifest_json)
    assert manifest.script_input_sha256 == _script_input_hash(
        "idea", cfg, "current research", None, [], None)


def test_unmanifested_legacy_title_is_preserved_as_editorial_input(
        tmp_path, monkeypatch):
    cfg = CurioConfig()
    paths = video_paths(str(tmp_path), "legacy-title")
    os.makedirs(os.path.dirname(paths.script_txt), exist_ok=True)
    with open(paths.script_txt, "w", encoding="utf-8") as stream:
        stream.write("Legacy script.")
    with open(paths.title_txt, "w", encoding="utf-8") as stream:
        stream.write("Title edited by a person?")
    monkeypatch.setattr(
        "curio.stages.research.verify_grounding",
        lambda *_args, **_kwargs: {"unverified": [], "checked": 0})
    monkeypatch.setattr(
        "curio.stages.script.generate_title",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unknown legacy title must not be overwritten")))

    result = run_script_stage(
        "idea", cfg, paths, None, research_prompt="research",
        research_target=None, research_sources=[], genre_directive=None,
        force=False)

    assert result.title.text == "Title edited by a person?"
    assert read_manifest(paths.script_manifest_json).title_origin == "legacy"
