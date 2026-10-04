import json
from types import SimpleNamespace

from curio.pipeline_scenes import run_scene_stage
from curio.stages.scene_contract import (ScenePlanResult, SemanticScene,
                                         TimelineSpan)
from curio.stages.scene_plan_artifact import (ScenePlanManifest,
                                              plan_to_dict,
                                              scene_plan_inputs_signature,
                                              write_manifest)


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
        return SimpleNamespace(
            semantic_scenes=tuple(scenes),
            changed=False, source="cache", applied=[])

    monkeypatch.setattr("curio.pipeline_scenes.enrich_scenes",
                        keep_enriched_scenes)
    result = run_scene_stage(
        "The black hole bends light.", SimpleNamespace(duration_target=0),
        SimpleNamespace(chapters_json=str(cache),
                         scene_plan_json=semantic_cache_path,
                         scene_plan_manifest_json=str(
                             tmp_path / "scene-plan-manifest.json")), force=False,
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
    assert (tmp_path / "scene-plan-manifest.json").is_file()


def test_semantic_plan_cache_is_canonical_over_legacy_chapters(tmp_path, monkeypatch):
    cache = tmp_path / "chapters.json"
    cache.write_text(json.dumps([{"id": 1, "narration": "Wrong legacy text.",
                                  "duration_estimate": 8}]), encoding="utf-8")
    semantic_cache = tmp_path / "scene-plan.json"
    cfg = SimpleNamespace(duration_target=0, language="pt-BR")
    signature = scene_plan_inputs_signature(
        "The black hole bends light.", cfg, genre="science",
        scene_target_seconds=9, max_scenes=None, scene_directive="", topic="",
        target=None, research_sources=[], research_timeout=1, etymology=None)
    manifest = tmp_path / "scene-plan-manifest.json"
    write_manifest(str(manifest), ScenePlanManifest(signature))
    semantic_scene = SemanticScene(
        id=1, narration="The black hole bends light.", source="local",
        planning_mode="deterministic", visual_type="conceptual",
        subject="black hole", visual_queries=("black hole lensing",))
    semantic_cache.write_text(json.dumps(plan_to_dict(ScenePlanResult(
        (semantic_scene,), (TimelineSpan(1, 4),), "local"))), encoding="utf-8")

    def enrich(scenes, **kwargs):
        return SimpleNamespace(semantic_scenes=tuple(scenes),
                               changed=False, source="cache", applied=[])

    monkeypatch.setattr("curio.pipeline_scenes.enrich_scenes", enrich)
    result = run_scene_stage(
        "The black hole bends light.", cfg,
        SimpleNamespace(chapters_json=str(cache),
                        scene_plan_json=str(semantic_cache),
                        scene_plan_manifest_json=str(manifest)), force=False,
        script_mode=True, genre="science", scene_target_seconds=9,
        max_scenes=None, scene_directive="", topic="", target=None,
        research_sources=[], research_timeout=1, etymology=None, metrics=None,
        warnings=[], write_json=_write_json)

    assert result.source == "cache"
    assert result.semantic_scenes[0].narration == "The black hole bends light."
    assert json.loads(cache.read_text(encoding="utf-8"))[0]["narration"] == \
        "The black hole bends light."


def test_scene_plan_cache_is_rebuilt_when_inputs_change(tmp_path, monkeypatch):
    script = "The black hole bends light."
    cache = tmp_path / "chapters.json"
    cache.write_text("[]", encoding="utf-8")
    plan_path = tmp_path / "scene-plan.json"
    plan_path.write_text(json.dumps(plan_to_dict(ScenePlanResult(
        (SemanticScene(id=1, narration=script, source="local",
                      planning_mode="deterministic"),),
        (TimelineSpan(1, 4),), "local"))), encoding="utf-8")
    cfg = SimpleNamespace(duration_target=0, language="pt-BR")
    manifest_path = tmp_path / "scene-plan-manifest.json"
    write_manifest(str(manifest_path), ScenePlanManifest("0" * 64))
    calls = []

    def build(*args, **kwargs):
        calls.append(kwargs)
        scene = SemanticScene(id=1, narration=script, source="planner",
                              planning_mode="deterministic")
        return ScenePlanResult((scene,), (TimelineSpan(1, 4),), "local")

    def enrich(scenes, **kwargs):
        return SimpleNamespace(semantic_scenes=tuple(scenes), changed=False,
                               source="planner", applied=[])

    monkeypatch.setattr("curio.pipeline_scenes.scenes_stage.build_semantic_scenes",
                        build)
    monkeypatch.setattr("curio.pipeline_scenes.scenes_stage.build_local_semantic_scenes",
                        build)
    monkeypatch.setattr("curio.pipeline_scenes.enrich_scenes", enrich)
    result = run_scene_stage(
        script, cfg,
        SimpleNamespace(chapters_json=str(cache), scene_plan_json=str(plan_path),
                        scene_plan_manifest_json=str(manifest_path)),
        force=False, script_mode=True, genre="science",
        scene_target_seconds=9, max_scenes=None, scene_directive="",
        topic="Black holes", target=None, research_sources=[],
        research_timeout=1, etymology=None, metrics=None, warnings=[],
        write_json=_write_json)

    assert calls
    assert result.source == "local"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["inputs_sha256"] != "0" * 64
