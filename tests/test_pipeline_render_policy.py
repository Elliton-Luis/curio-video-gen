from curio.pipeline_render import final_cache_is_current


def _current(**changes):
    values = {
        "output_exists": True,
        "force": False,
        "subtitles_changed": False,
        "transition_dirty": False,
        "narration_reused": True,
        "audio_cache_matches": True,
    }
    values.update(changes)
    return final_cache_is_current(**values)


def test_final_cache_requires_reused_current_narration():
    assert _current()
    assert not _current(narration_reused=False)


def test_final_cache_rejects_each_changed_embedded_input():
    for changed in ({"force": True}, {"subtitles_changed": True},
                    {"transition_dirty": True},
                    {"audio_cache_matches": False},
                    {"output_exists": False}):
        assert not _current(**changed)
