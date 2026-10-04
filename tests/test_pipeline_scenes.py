import json
from types import SimpleNamespace

from curio.pipeline_scenes import run_scene_stage
from curio.stages.scene_contract import (ScenePlanResult, SemanticScene,
                                         TimelineSpan)
from curio.stages.scene_plan_artifact import plan_to_dict
from curio.stages.scenes import Chapter


def _write_json(path, value):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh)


def test_legacy_cache_recovery_is_persisted_and_invalidates_media(tmp_path, monkeypatch):
    cache = tmp_path / "chapters.json"
    semantic_cache = tmp_path / "scene-plan.json"
    cache.write_text(json.dumps([{
        "id": 1,
        "narration": "The black hole bends light.",
        "duration_estimate": 4,
    }]), encoding="utf-8")
    semantic_cache_path = str(semantic_cache)
    chapter = None

    def keep_enriched_scenes(scenes, **kwargs):
        nonlocal chapter
        chapter = Chapter.from_semantic_scene(
            scenes[0], timing=kwargs["timeline_spans"][0])
        return SimpleNamespace(
            chapters=(chapter,), semantic_scenes=tuple(scenes),
            changed=False, source="cache", applied=[])

    monkeypatch.setattr("curio.pipeline_scenes.enrich_scenes",
                        keep_enriched_scenes)
    result = run_scene_stage(
        "The black hole bends light.", SimpleNamespace(duration_target=0),
        SimpleNamespace(chapters_json=str(cache),
                         scene_plan_json=semantic_cache_path), force=False,
        script_mode=True, genre="science", scene_target_seconds=9,
        max_scenes=None, scene_directive="", topic="", target=None,
        research_sources=[], research_timeout=1, etymology=None, metrics=None,
        warnings=[], write_json=_write_json)

    saved = json.loads(cache.read_text(encoding="utf-8"))[0]
    assert result.source == "cache"
    assert result.invalidate_media is True
    assert result.semantic_scenes[0].planning_mode == "deterministic"
    assert saved["representations"][0]["source"] == "legacy_local_recovery"
    assert json.loads(semantic_cache.read_text(encoding="utf-8"))["schema_version"] == 1


def test_semantic_plan_cache_is_canonical_over_legacy_chapters(tmp_path, monkeypatch):
    cache = tmp_path / "chapters.json"
    cache.write_text(json.dumps([{"id": 1, "narration": "Wrong legacy text.",
                                  "duration_estimate": 8}]), encoding="utf-8")
    semantic_cache = tmp_path / "scene-plan.json"
    semantic_scene = SemanticScene(
        id=1, narration="The black hole bends light.", source="local",
        planning_mode="deterministic", visual_type="conceptual",
        subject="black hole", visual_queries=("black hole lensing",))
    semantic_cache.write_text(json.dumps(plan_to_dict(ScenePlanResult(
        (semantic_scene,), (TimelineSpan(1, 4),), "local"))), encoding="utf-8")

    def enrich(scenes, **kwargs):
        chapter = Chapter.from_semantic_scene(scenes[0],
                                               timing=kwargs["timeline_spans"][0])
        return SimpleNamespace(chapters=(chapter,), semantic_scenes=tuple(scenes),
                               changed=False, source="cache", applied=[])

    monkeypatch.setattr("curio.pipeline_scenes.enrich_scenes", enrich)
    result = run_scene_stage(
        "The black hole bends light.", SimpleNamespace(duration_target=0),
        SimpleNamespace(chapters_json=str(cache),
                        scene_plan_json=str(semantic_cache)), force=False,
        script_mode=True, genre="science", scene_target_seconds=9,
        max_scenes=None, scene_directive="", topic="", target=None,
        research_sources=[], research_timeout=1, etymology=None, metrics=None,
        warnings=[], write_json=_write_json)

    assert result.source == "cache"
    assert result.semantic_scenes[0].narration == "The black hole bends light."
    assert json.loads(cache.read_text(encoding="utf-8"))[0]["narration"] == \
        "The black hole bends light."
