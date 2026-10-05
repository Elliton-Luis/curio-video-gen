from curio.media.artifacts import (
    MediaSelectionManifest,
    SELECTION_POLICY_VERSION,
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
    second.set_visual_queries(["Mohács painting"], source="test_fixture")
    assert signature != media_selection_signature(
        [second], "history", 2, ["wikimedia"], 35)


def test_media_selection_signature_tracks_planning_provenance():
    llm = Chapter(id=1, narration="Batalha de Mohács.", duration_estimate=8,
                  planning_mode="llm",
                  visual_queries=["Battle of Mohács"])
    local = Chapter(id=1, narration=llm.narration, duration_estimate=8,
                    planning_mode="deterministic",
                    visual_queries=list(llm.visual_queries))
    assert media_selection_signature([llm], "history", 2, ["wikimedia"], 35) != (
        media_selection_signature([local], "history", 2, ["wikimedia"], 35))


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
    manifest = MediaSelectionManifest(1, SELECTION_POLICY_VERSION,
                                      "abc", (1, 2), ("a", "b"))
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


def test_selection_metrics_use_scene_decision_and_identity_not_render_beats():
    from curio.media.selection_metrics import MediaSelectionStats

    repeated = {"asset_id": "map", "provider": "wikimedia",
                "source_url": "https://museum.test/map"}
    unique = {"asset_id": "portrait", "provider": "met",
              "source_url": "https://museum.test/portrait"}
    scenes = [
        {"chapter_id": 1, "asset": repeated,
         "visual_decision": {"selection": {"status": "real"}}},
        {"chapter_id": 2, "asset": repeated,
         "visual_decision": {"selection": {"status": "reused"}}},
        {"chapter_id": 3,
         "asset": {"asset_id": "synth-1", "provider": "synth"},
         "visual_decision": {"selection": {"status": "synthetic"}}},
        {"chapter_id": 4, "asset": unique,
         "visual_decision": {"selection": {"status": "real"}}},
    ]

    from curio.media.selection_metrics import MediaMetricsInput
    stats = MediaSelectionStats.from_input(
        MediaMetricsInput.from_persisted_rows(scenes))

    assert stats.unique_assets == 2
    assert stats.reused_assets == 1
    assert stats.reuse_count == 1
    assert stats.unique_asset_ratio == 0.667
    assert stats.scenes_with_new_asset == 2
    assert stats.scenes_with_reused_asset == 1
    assert stats.synthetic_scenes == 1
    assert stats.scenes_with_unknown_decision == 0


def test_missing_backfill_selection_stays_unknown_not_zero(tmp_path):
    from curio.metrics import backfill_from_metadata

    result = backfill_from_metadata("old", {}, str(tmp_path / "metrics"))
    import json
    with open(result, encoding="utf-8") as fh:
        report = json.load(fh)["pipeline"]["visual_report"]

    assert report["unique_assets"] is None
    assert report["synthetic_scenes"] is None
    assert report["sem_visual"] is None
