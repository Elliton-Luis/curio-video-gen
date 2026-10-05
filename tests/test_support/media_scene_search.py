"""Compatibility projection for tests of the private scene-search helper."""

from curio.media.selection_result import SceneMediaSelection


def search_scene_rows(visual_module, *args, **kwargs):
    selection, warnings = visual_module._search_scene_with_shortcircuit(
        *args, **kwargs)
    assert isinstance(selection, SceneMediaSelection)
    return [selection.to_dict()], warnings
