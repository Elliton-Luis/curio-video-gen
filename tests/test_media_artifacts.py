from curio.media.artifacts import (
    MediaSelectionManifest,
    media_selection_signature,
    selection_cache_is_current,
    write_manifest,
)
from curio.stages.scenes import Chapter


def test_media_selection_signature_tracks_semantics_but_not_timing():
    first = Chapter(id=1, narration="Batalha de Mohács.", duration_estimate=8,
                    visual_queries=["Battle of Mohács"])
    second = Chapter(id=1, narration="Batalha de Mohács.", duration_estimate=8,
                     visual_queries=["Battle of Mohács"], start=1, end=9)

    signature = media_selection_signature([first], "history", 2,
                                          ["wikimedia"], 35)
    assert signature == media_selection_signature(
        [second], "history", 2, ["wikimedia"], 35)
    second.visual_queries = ["Mohács painting"]
    assert signature != media_selection_signature(
        [second], "history", 2, ["wikimedia"], 35)


def test_media_selection_signature_tracks_acquisition_policy():
    chapter = Chapter(id=1, narration="Janízaros.", duration_estimate=5)
    signature = media_selection_signature([chapter], "history", 2,
                                          ["wikimedia"], 35)
    assert signature != media_selection_signature(
        [chapter], "history", 3, ["wikimedia"], 35)
    assert signature != media_selection_signature(
        [chapter], "history", 2, ["met", "wikimedia"], 35)
    assert signature != media_selection_signature(
        [chapter], "history", 2, ["wikimedia"], 40)


def test_manifest_requires_current_schema_policy_signature_and_scenes():
    manifest = MediaSelectionManifest(1, 1, "abc", (1, 2), ("a", "b"))
    assert manifest.matches("abc", [1, 2])
    assert not manifest.matches("stale", [1, 2])
    assert not manifest.matches("abc", [1])
    assert not MediaSelectionManifest(1, 0, "abc", (1, 2), ()).matches(
        "abc", [1, 2])


def test_acquired_cache_requires_manifest_but_explicit_manual_selection_survives(tmp_path):
    manifest_path = str(tmp_path / "media-selection.json")
    acquired = [{"chapter_id": 1,
                 "asset": {"asset_id": "a", "provider": "wikimedia"},
                 "assets": []}]
    manual = [{"chapter_id": 1,
               "asset": {"asset_id": "a", "provider": "manual"},
               "assets": []}]

    assert not selection_cache_is_current(acquired, manifest_path, "abc", [1])
    write_manifest(manifest_path, acquired, "abc")
    assert selection_cache_is_current(acquired, manifest_path, "abc", [1])
    assert not selection_cache_is_current(acquired, manifest_path, "changed", [1])
    assert selection_cache_is_current(manual, manifest_path, "abc", [1])
