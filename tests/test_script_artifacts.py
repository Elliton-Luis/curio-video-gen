import pytest

from curio.script_artifacts import (ScriptArtifactsManifest, read_manifest,
                                    text_identity, write_manifest)


def test_script_artifact_manifest_round_trip(tmp_path):
    manifest = ScriptArtifactsManifest(
        script_sha256=text_identity("Script"), script_origin="edited",
        title_sha256=text_identity("Title"), title_origin="generated",
        title_script_sha256=text_identity("Script"))
    path = tmp_path / "script" / "artifacts.json"

    write_manifest(str(path), manifest)

    assert read_manifest(str(path)) == manifest


def test_script_artifact_manifest_rejects_incomplete_hashes():
    with pytest.raises(ValueError, match="SHA-256"):
        ScriptArtifactsManifest(
            script_sha256="unknown", script_origin="cache",
            title_sha256=text_identity("Title"), title_origin="cache",
            title_script_sha256=None)


def test_manifest_v1_loads_with_unknown_generation_inputs():
    manifest = ScriptArtifactsManifest.from_dict({
        "schema_version": 1,
        "script": {"sha256": text_identity("Script"), "origin": "template"},
        "title": {"sha256": text_identity("Title"), "origin": "generated",
                  "script_sha256": text_identity("Script")},
    })

    assert manifest.script_input_sha256 is None
    assert manifest.title_input_sha256 is None
    assert manifest.to_dict()["schema_version"] == 2


def test_manifest_rejects_malformed_input_signature():
    with pytest.raises(ValueError, match="input hashes"):
        ScriptArtifactsManifest(
            script_sha256=text_identity("Script"), script_origin="template",
            title_sha256=text_identity("Title"), title_origin="generated",
            title_script_sha256=None, script_input_sha256="bad")
