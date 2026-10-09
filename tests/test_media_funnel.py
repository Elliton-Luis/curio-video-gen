"""Contagens reconciliáveis sem alterar decisões de seleção de mídia."""

from curio.config import CurioConfig
from curio.media.providers import MediaAsset
from curio.metrics import RunMetrics
from curio.stages import media_acquisition, visual, scoring
from tests.test_support.media_scene_search import search_scene_rows
from curio.stages.scene_projection import Chapter
from tests.test_support.search_plan import patch_search_plan


def test_funnel_counts_each_loss_once_and_does_not_double_search(monkeypatch, tmp_path):
    def asset(key, title, license="CC0"):
        return MediaAsset(provider="fixture", asset_id=key, title=title,
                          download_url=f"https://example.test/{key}.jpg",
                          license=license, width=1600, height=1600)

    blocked = asset("blocked", "receipt", "All rights reserved")
    results = [blocked, blocked, asset("low", "mountain"),
               asset("good", "receipt"), asset("unused1", "receipt"),
               asset("unused2", "receipt")]

    class Provider:
        name = "fixture"

        def search(self, query, limit, metrics):
            metrics.media_search(self.name)
            return results

    monkeypatch.setattr(visual, "CANDIDATE_MULTIPLIER", 2)
    patch_search_plan(monkeypatch, visual, ["receipt"])
    monkeypatch.setattr(scoring, "threshold", lambda: 34)
    monkeypatch.setattr(media_acquisition, "downloaded_dimensions_valid", lambda asset: True)
    from curio.media import cache
    monkeypatch.setattr(cache, "_fetch",
                        lambda url, provider="", metrics=None: b"fixture")
    monkeypatch.setattr(cache.time, "sleep", lambda delay: None)
    ch = Chapter(1, "Receipt.", 3, subject="receipt")
    metrics = RunMetrics("fixture", "receipt", "ai")
    cfg = CurioConfig(cache_dir=str(tmp_path))
    scenes, _ = search_scene_rows(visual,
        ch, [Provider()], cfg, 1, metrics, str(tmp_path))
    assert metrics.media_searches == {"fixture": 1}
    assert metrics.media_funnel == {
        "normalized_returned": 6, "unique_considered": 5,
        "hard_rejected": 1, "duplicates": 1, "eligible": 4,
        "score_rejected": 1, "above_threshold": 3,
        "selected": 1, "used_real": 1,
    }
    assert metrics.media_assets_rejected == 2
    assert sum(metrics.media_rejections.values()) == 2
    assert metrics.media_rights_blocked == 1
    assert metrics.media_downloads == 1
    assert scenes[0]["asset"]["asset_id"] == "good"
    media = metrics.to_dict({"media": scenes}, {}, "metrics")["consumption"]["media"]
    assert media["funnel"] == metrics.media_funnel
    assert media["rejection_reasons"] == metrics.media_rejections


def test_generic_candidate_passes_on_own_terms_after_specifics(monkeypatch, tmp_path):
    def asset(key, title):
        return MediaAsset(provider="fixture", asset_id=key, title=title,
                          download_url=f"https://example.test/{key}.jpg",
                          license="CC0", width=1600, height=1600)

    class Provider:
        name = "fixture"

        def search(self, query, limit, metrics):
            metrics.media_search(self.name)
            if query == "church interior":
                return [asset("g1", "church interior altar")]
            return [asset("s1", "unrelated warehouse boxes")]

    monkeypatch.setattr(visual, "CANDIDATE_MULTIPLIER", 4)
    patch_search_plan(monkeypatch, visual,
                      ["specific query", "church interior"], ["church interior"])
    monkeypatch.setattr(scoring, "threshold", lambda: 34)
    monkeypatch.setattr(media_acquisition, "downloaded_dimensions_valid", lambda asset: True)
    from curio.media import cache
    monkeypatch.setattr(cache, "_fetch",
                        lambda url, provider="", metrics=None: b"fixture")
    monkeypatch.setattr(cache.time, "sleep", lambda delay: None)
    ch = Chapter(1, "Tomás de Aquino nasceu em 1225.", 5,
                 subject="Tomás de Aquino")
    metrics = RunMetrics("fixture", "tomas", "ai")
    cfg = CurioConfig(cache_dir=str(tmp_path))
    scenes, _ = search_scene_rows(visual,
        ch, [Provider()], cfg, 1, metrics, str(tmp_path))
    picked = scenes[0]["assets"][0]
    assert picked["generic"] is True
    assert scenes[0]["asset"]["asset_id"] == "g1"
    assert metrics.media_funnel.get("generic_used") == 1


def test_semantic_rejections_do_not_consume_scene_candidate_budget(
        monkeypatch, tmp_path):
    def asset(key, title):
        return MediaAsset(provider="fixture", asset_id=key, title=title,
                          download_url=f"https://example.test/{key}.jpg",
                          license="CC0", width=1600, height=1200)

    class Provider:
        name = "fixture"

        def search(self, query, limit, metrics):
            metrics.media_search(self.name)
            if query == "first broad query":
                return [asset("irrelevant", "Unrelated warehouse photograph")]
            return [asset("specific", "Battle of Mohacs 1526 Ottoman Empire engraving")]

    monkeypatch.setattr(visual, "MAX_SCENE_CANDIDATES", 1)
    monkeypatch.setattr(visual, "CANDIDATE_MULTIPLIER", 1)
    patch_search_plan(monkeypatch, visual,
                      ["first broad query", "Battle of Mohacs Ottoman Empire"])
    monkeypatch.setattr(scoring, "threshold", lambda: 34)
    monkeypatch.setattr(media_acquisition, "downloaded_dimensions_valid",
                        lambda _asset: True)
    from curio.media import cache
    monkeypatch.setattr(cache, "_fetch",
                        lambda url, provider="", metrics=None: b"fixture")
    monkeypatch.setattr(cache.time, "sleep", lambda _delay: None)

    from curio.stages.scene_contract import SemanticScene, VideoContext, VisualRepresentation
    scene = SemanticScene(
        id=1, narration="Battle of Mohacs in 1526.", planning_mode="llm",
        subject="Battle of Mohacs", event="Battle of Mohacs",
        representations=(VisualRepresentation(
            "Battle of Mohacs 1526", kind="event", level=1, source="planner"),),
        video_context=VideoContext(topic="Ottoman Empire", events=("Battle of Mohacs",)))
    metrics = RunMetrics("fixture", "Mohacs", "local")
    cfg = CurioConfig(cache_dir=str(tmp_path))
    selection, _warnings = visual._search_scene_with_shortcircuit(
        scene, visual.build_visual_plan(scene),
        visual.build_search_plan(visual.build_visual_plan(scene)),
        [Provider()], cfg, 1, metrics, str(tmp_path))

    row = selection.to_dict()
    assert row["asset"]["asset_id"] == "specific"
    query_audit = row["visual_decision"]["queries"]
    assert [item["status"] for item in query_audit] == ["consulted", "consulted"]
    assert query_audit[0]["outcome"] == "eligible"
    assert query_audit[1]["outcome"] == "eligible"
    candidate_rows = row["visual_decision"]["candidates"]
    first = next(item for item in candidate_rows
                 if item["query"] == "first broad query")
    assert first["decision"] == "rejected"
    assert metrics.media_funnel.get("score_rejected") == 1


def test_synthetic_percentage_counts_generated_assets_not_scene_type():
    metrics = RunMetrics("fixture", "receipt", "ai")
    metrics.media_record_visual_type("historical_art")
    metrics.media_record_fallback("form")
    metrics.media_synthetic_assets = 1
    assert metrics.media_visual_report(1)["gerado_por_codigo_pct"] == 100.0


def test_unsplash_jpg_transform_is_not_rejected_for_missing_extension():
    from curio.stages import media_rules
    asset = MediaAsset(provider="unsplash", asset_id="photo", title="receipt",
                       download_url="https://images.unsplash.com/photo-123?w=1920&q=80&fm=jpg",
                       license="Licença Unsplash (uso livre)", width=1600, height=1600)
    assert media_rules.asset_gate_reason(asset, []) == ""
    for url in ("https://example.test/page?fm=jpg",
                "https://images.unsplash.com/photo-123?fm=html",
                "https://images.unsplash.com/photo-123",
                "https://images.unsplash.com.evil.test/photo-123?fm=jpg"):
        asset.download_url = url
        assert media_rules.asset_gate_reason(asset, []) == "não é imagem (jpg/png/webp)"
