import subprocess

from curio.config import CurioConfig
from curio.metrics import RunMetrics
from curio.stages import visual, visual_timeline, render
from curio.stages.scenes import Chapter
from curio.stages.visual_beats import asset_key


def entry(index, path=""):
    return {"asset": {"asset_id": str(index), "provider": "fixture",
                      "title": "Rome statue", "local_path": path, "kind": "image"},
            "score": 75, "query": "rome statue", "acquisition": "cache"}


def test_all_selected_backgrounds_survive_sparse_insert_budget():
    chapters = [Chapter(1, "Rome", 8, start=0, end=8)]
    media = [{"chapter_id": 1, "assets": [entry(i) for i in range(3)]}]
    timeline = visual.build_visual_timeline(chapters, media, insertions=0)
    assert len(timeline[0]["images"]) == 1
    assert len(timeline[0]["backgrounds"]) == 3
    keys = {key for beat in timeline[0]["visual_beats"] for key in beat["asset_ids"]}
    assert keys == {"fixture:0", "fixture:1", "fixture:2"}
    metrics = RunMetrics("test", "Rome", "ai")
    metrics.visual_plan(chapters, media, 2.1, timeline)
    assert metrics.media_available_ids == metrics.visual_asset_ids == keys
    assert sum(metrics.visual_asset_beat_counts.values()) == len(timeline[0]["visual_beats"])
    assert metrics.media_available_acquisitions == {"cache": 3}
    report = metrics.to_dict({"artifacts": {}}, {}, "metrics")["pipeline"]
    assert report["visual_assets_reused"] == 0  # Holding a photo across camera beats is not reselection.


def test_selection_uses_fresh_eligible_candidates_across_scenes(monkeypatch, tmp_path):
    from curio.media.providers import MediaAsset
    assets = []
    for i in range(4):
        path = tmp_path / f"{i}.png"
        path.write_bytes(b"fixture")
        assets.append(MediaAsset(provider="fixture", asset_id=str(i), title="Rome statue",
                                 local_path=str(path), download_url=f"https://fixture.test/{i}.png",
                                 license="CC0", width=2000, height=2000))
    class Provider:
        name = "fixture"
        def search(self, *args, **kwargs):
            return assets
    monkeypatch.setattr(visual, "_downloaded_dims_ok", lambda *args: True)
    monkeypatch.setattr(visual, "_waterfall_queries", lambda *args: (["rome statue"], set()))
    uses = {}
    picked = []
    for index in range(2):
        result, _ = visual._search_scene_with_shortcircuit(
            Chapter(index + 1, "Rome statue", 8, subject="Rome"), [Provider()],
            CurioConfig(), 2, None, str(tmp_path), asset_uses=uses)
        picked.extend(asset_key(item["asset"]) for item in result[0]["assets"])
    assert len(set(picked)) == 4


def test_provider_ids_do_not_collide():
    assert asset_key({"provider": "one", "asset_id": "1"}) != asset_key({
        "provider": "two", "asset_id": "1"})


def test_real_render_switches_all_backgrounds(tmp_path):
    cfg = CurioConfig(width=96, height=170, fps=10, render_backend="cpu")
    chapters = [Chapter(1, "Rome", 6.3, start=0, end=6.3)]
    entries = []
    for index, color in enumerate(("red", "lime", "blue")):
        path = tmp_path / f"{index}.png"
        size = ("100x170", "96x172", "94x168")[index]
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"color=c={color}:s={size}", "-frames:v", "1", str(path)], check=True)
        entries.append(entry(index, str(path)))
    timeline = visual.build_visual_timeline(
        chapters, [{"chapter_id": 1, "assets": entries}], insertions=0)
    scene = timeline[0]
    output = tmp_path / "varied.mp4"
    render.render_collage_segment(scene["images"], 6.3, str(output), cfg,
                                  backgrounds=scene["backgrounds"])
    for time, channel in ((1., 0), (3., 1), (5., 2)):
        result = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(time), "-i", str(output),
                                 "-frames:v", "1", "-vf", "crop=2:2:40:80,format=rgb24",
                                 "-f", "rawvideo", "-"], capture_output=True, check=True)
        assert result.stdout[channel] > 150
        assert all(result.stdout[c] < 80 for c in range(3) if c != channel)


def test_segment_cache_tracks_asset_identity_and_render_size(tmp_path):
    from curio.pipeline_render import _segment_identity
    cfg = CurioConfig()
    path = tmp_path / "asset.png"
    path.write_bytes(b"first")
    asset = {"local_path": str(path)}
    first = _segment_identity([asset], cfg, 0)
    path.write_bytes(b"other contents")
    assert _segment_identity([asset], cfg, 0) != first
    cfg.width = 480
    assert _segment_identity([asset], cfg, 0) != first


def test_central_entity_is_not_blacklisted_by_its_own_name():
    from curio.stages.entity import TargetEntity
    from curio.stages import media_rules, scoring
    target = TargetEntity("Júlio César", aliases=["Julius Caesar"],
                          forbidden=["Júlio", "César", "César filme", "Júlio César Jacobi"])
    assert target.forbidden == ["César filme", "Júlio César Jacobi"]
    ch = Chapter(1, "Júlio César chegou ao poder.", 8, subject="Júlio César",
                 subject_aliases=["Julius Caesar"], forbidden=["Júlio", "César"])
    asset = {"title": "Julius Caesar Roman marble bust"}
    assert not media_rules.rejection_reason(asset, media_rules.scene_blocklist(ch))
    assert scoring.base_score(asset, ch)["score"] >= scoring.threshold()


def test_missing_science_context_uses_verified_topic_and_english_alias(monkeypatch):
    from curio.stages.entity import TargetEntity
    from curio.stages.research import ResearchSource
    from curio.stages.visual_context import fill_missing_context
    monkeypatch.setattr("curio.stages.research._get_json", lambda *a, **kw: {
        "query": {"pages": {"1": {"langlinks": [{"lang": "en", "*": "Black hole"}]}}}})
    ch = Chapter(1, "Nem a luz escapa de um buraco negro.", 8)
    source = ResearchSource(title="Buraco negro", url="https://pt.wikipedia.org/wiki/Buraco_negro",
                            snippet="Buraco negro é um objeto astronômico.")
    assert fill_missing_context([ch], TargetEntity("buraco negro", is_entity=False),
                                "science", [source])
    assert ch.subject == "buraco negro" and "Black hole" in ch.subject_aliases
    assert ch.visual_queries[0] == "Black hole"
    assert ch.narration == "Nem a luz escapa de um buraco negro."


def test_mythological_medusa_rejects_marine_homonym():
    from curio.stages import media_rules
    ch = Chapter(1, "Medusa era uma górgona.", 8, subject="Medusa")
    assert media_rules.rejection_reason({"title": "Medusa jellyfish sea animal"},
                                        media_rules.scene_blocklist(ch))
    assert not media_rules.rejection_reason({"title": "Medusa Greek sculpture"},
                                            media_rules.scene_blocklist(ch))


def test_literal_rome_context_keeps_maps_and_artifacts_eligible(monkeypatch):
    from curio.stages.entity import TargetEntity
    from curio.stages.visual_context import fill_missing_context
    from curio.stages import scoring
    ch = Chapter(1, "Júlio César chegou em Roma.", 8)
    assert fill_missing_context([ch], TargetEntity("Júlio César"), "people")
    assert ch.subject == "Roma" and "rome" in ch.subject_aliases
    assets = [entry(i) for i in range(3)]
    for item, title in zip(assets, ("Rome Julius Caesar bust", "Rome Roman Republic map", "Rome ancient coin")):
        item["asset"]["title"] = title
        assert scoring.base_score(item["asset"], ch)["score"] >= scoring.threshold()
    ch.start, ch.end = 0, 8
    timeline = visual.build_visual_timeline([ch], [{"chapter_id": 1, "assets": assets}], insertions=0)
    assert len(timeline[0]["backgrounds"]) == 3


def test_retiming_preserves_background_variety():
    ch = Chapter(1, "Rome", 8, start=0, end=8)
    timeline = visual.build_visual_timeline([ch], [{"chapter_id": 1, "assets":
                                                  [entry(i) for i in range(3)]}], insertions=0)
    ch.start, ch.end = 2, 14
    updated = visual_timeline.retime_visual_timeline(timeline, [ch])[0]
    assert {asset_key(im) for im in updated["backgrounds"]} == {"fixture:0", "fixture:1", "fixture:2"}
    assert updated["visual_beats"][0]["start"] == 2
    assert updated["visual_beats"][-1]["end"] == 14


def test_metrics_exclude_assets_after_final_audio_cut():
    ch = Chapter(1, "Rome", 8, start=0, end=8)
    media = [{"chapter_id": 1, "assets": [entry(i) for i in range(3)]}]
    timeline = visual.build_visual_timeline([ch], media, insertions=0)
    metrics = RunMetrics("test", "Rome", "human")
    metrics.visual_plan([ch], media, 2.1, timeline, rendered_duration=1.5)
    assert len(metrics.media_available_ids) == 3
    assert len(metrics.visual_asset_ids) == 1
    assert metrics.visual_asset_beat_counts == {"fixture:0": 1, "fixture:1": 0, "fixture:2": 0}


def test_camera_motion_is_linear_drift_without_oscillation():
    from curio.stages.render import _beat_zoompan
    zoom = _beat_zoompan(30, 189, variant=0)
    pan = _beat_zoompan(30, 189, variant=1)
    assert "sin" not in zoom and "cos" not in zoom
    assert "sin" not in pan and "cos" not in pan
    assert "on/189" in zoom  # zoom linear até o fim do segmento
    assert "on/189" in pan  # pan linear até o fim do segmento
    assert zoom != pan  # variantes alternam zoom e pan
