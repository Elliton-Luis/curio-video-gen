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
