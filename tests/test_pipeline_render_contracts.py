import pytest

from curio.media.selection_result import MediaStageResult
from curio.pipeline_render import SceneRenderPlan
from curio.stages.scene_contract import SemanticScene


def test_render_plan_projects_validated_media_selection():
    result = MediaStageResult.from_rows([{
        "chapter_id": 1,
        "asset": {"provider": "wikimedia", "asset_id": "map-1",
                  "local_path": "/cache/map.jpg", "kind": "image"},
        "assets": [],
    }], "provider")

    plan = SceneRenderPlan.from_media_result(result)

    assert plan.scenes[0].scene_id == 1
    assert plan.scenes[0].asset.local_path == "/cache/map.jpg"
    assert plan.for_scenes((SemanticScene(1, "A scene."),))[1].kind == "image"


def test_persisted_adapter_preserves_legacy_renderable_asset_without_identity():
    plan = SceneRenderPlan.from_persisted_rows([{
        "chapter_id": 1,
        "asset": {"local_path": "/old-project/photo.jpg"},
    }])

    assert plan.scenes[0].asset.local_path == "/old-project/photo.jpg"
    assert plan.scenes[0].asset.kind == "image"


@pytest.mark.parametrize("rows, error", [
    ({}, TypeError),
    ([{"chapter_id": True, "asset": None}], ValueError),
    ([{"chapter_id": 1}, {"chapter_id": 1}], ValueError),
    ([{"chapter_id": 1, "asset": "bad"}], TypeError),
])
def test_persisted_render_adapter_rejects_invalid_scene_rows(rows, error):
    with pytest.raises(error):
        SceneRenderPlan.from_persisted_rows(rows)
