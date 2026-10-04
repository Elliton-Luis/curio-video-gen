import json
from types import SimpleNamespace

from curio.pipeline_scenes import run_scene_stage


def _write_json(path, value):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh)


def test_legacy_cache_recovery_is_persisted_and_invalidates_media(tmp_path, monkeypatch):
    cache = tmp_path / "chapters.json"
    cache.write_text(json.dumps([{
        "id": 1,
        "narration": "The black hole bends light.",
        "duration_estimate": 4,
    }]), encoding="utf-8")
    chapter = None

    def keep_enriched_scenes(chapters, **kwargs):
        nonlocal chapter
        chapter = chapters[0]
        return SimpleNamespace(scenes=chapters, changed=False, source="cache",
                               applied=[])

    monkeypatch.setattr("curio.pipeline_scenes.enrich_scenes",
                        keep_enriched_scenes)
    result = run_scene_stage(
        "The black hole bends light.", SimpleNamespace(duration_target=0),
        SimpleNamespace(chapters_json=str(cache)), force=False,
        script_mode=True, genre="science", scene_target_seconds=9,
        max_scenes=None, scene_directive="", topic="", target=None,
        research_sources=[], research_timeout=1, etymology=None, metrics=None,
        warnings=[], write_json=_write_json)

    saved = json.loads(cache.read_text(encoding="utf-8"))[0]
    assert result.source == "cache"
    assert result.invalidate_media is True
    assert result.semantic_scenes[0].planning_mode == "deterministic"
    assert saved["representations"][0]["source"] == "legacy_local_recovery"
