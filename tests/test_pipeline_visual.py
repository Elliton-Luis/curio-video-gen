import json
import os
from types import SimpleNamespace

from curio.media.artifacts import media_selection_signature, write_manifest
from curio.pipeline_visual import resolve_media
from curio.stages.scenes import Chapter
from curio.stages.scoring import threshold


def _scene():
    return Chapter(id=1, narration="Uma cena sobre Marte.", duration_estimate=5,
                   subject="Marte",
                   planning_mode="deterministic").semantic_scene()


def _paths(tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    return SimpleNamespace(
        root=str(tmp_path), media_json=str(media_dir / "media.json"),
        media_manifest_json=str(media_dir / "media-selection.json"))


def _asset(path):
    return {"provider": "synth", "asset_id": "diagram-1",
            "title": "Marte", "local_path": str(path)}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def test_resolve_media_consumes_only_cache_with_current_manifest(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    scene = _scene()
    image = tmp_path / "diagram.png"
    image.write_bytes(b"visual")
    asset = _asset(image)
    selected = [{"chapter_id": 1, "asset": asset,
                 "assets": [{"asset": asset, "query": "Mars"}],
                 "visual_decision": {"selected": asset}}]
    signature = media_selection_signature([scene], "science", 1,
                                          ["wikimedia"], threshold())
    with open(paths.media_json, "w", encoding="utf-8") as fh:
        json.dump(selected, fh)
    write_manifest(paths.media_manifest_json, selected, signature)
    monkeypatch.setattr("curio.pipeline_visual.get_providers",
                        lambda _cfg: [SimpleNamespace(name="wikimedia")])
    monkeypatch.setattr("curio.pipeline_visual.visual_stage.fetch_media_multi",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("current project selection must be reused")))

    result = resolve_media([scene], SimpleNamespace(), paths, 1, "science",
                           metrics=None, force=False, write_json=_write_json)

    assert result.source == "project-cache"
    assert result.scenes == selected


def test_resolve_media_researches_when_manifest_signature_is_stale(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    scene = _scene()
    image = tmp_path / "diagram.png"
    image.write_bytes(b"visual")
    asset = _asset(image)
    selected = [{"chapter_id": 1, "asset": asset,
                 "assets": [{"asset": asset, "query": "Mars"}],
                 "visual_decision": {"selected": asset}}]
    with open(paths.media_json, "w", encoding="utf-8") as fh:
        json.dump(selected, fh)
    write_manifest(paths.media_manifest_json, selected, "old-signature")
    monkeypatch.setattr("curio.pipeline_visual.get_providers",
                        lambda _cfg: [SimpleNamespace(name="wikimedia")])
    calls = []

    def fetch(*args, **kwargs):
        calls.append((args, kwargs))
        return selected, ["refresh"]

    monkeypatch.setattr("curio.pipeline_visual.visual_stage.fetch_media_multi", fetch)

    result = resolve_media([scene], SimpleNamespace(), paths, 1, "science",
                           metrics=None, force=False, write_json=_write_json)

    assert result.source == "provider"
    assert result.warnings == ["refresh"]
    assert len(calls) == 1
    assert json.loads(open(paths.media_manifest_json, encoding="utf-8").read())[
        "input_signature"] != "old-signature"
