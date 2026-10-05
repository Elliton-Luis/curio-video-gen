"""Compatibility projection for tests of the private scene-search helper."""

from curio.media.selection_result import SceneMediaSelection


def search_scene_rows(visual_module, *args, **kwargs):
    scene = args[0]
    visual_plan = visual_module.build_visual_plan(scene)
    search_plan = visual_module.build_search_plan(
        visual_plan, kwargs.get("genre", ""))
    args = (scene, visual_plan, search_plan, *args[1:])
    selection, warnings = visual_module._search_scene_with_shortcircuit(
        *args, **kwargs)
    assert isinstance(selection, SceneMediaSelection)
    return [selection.to_dict()], warnings
