"""Contagens reconciliáveis sem alterar decisões de seleção de mídia."""

from curio.config import CurioConfig
from curio.media.providers import MediaAsset
from curio.metrics import RunMetrics
from curio.stages import visual, scoring
from curio.stages.scenes import Chapter


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
    monkeypatch.setattr(visual, "_waterfall_queries", lambda ch: ["receipt"])
    monkeypatch.setattr(scoring, "threshold", lambda: 34)
    monkeypatch.setattr(visual, "_downloaded_dims_ok", lambda asset: True)
    from curio.media import cache
    monkeypatch.setattr(cache, "_fetch", lambda url, provider="": b"fixture")
    monkeypatch.setattr(cache.time, "sleep", lambda delay: None)
    ch = Chapter(1, "Receipt.", 3, subject="receipt")
    metrics = RunMetrics("fixture", "receipt", "ai")
    cfg = CurioConfig(cache_dir=str(tmp_path))
    scenes, _ = visual._search_scene_with_shortcircuit(
        ch, [Provider()], cfg, 1, metrics, str(tmp_path))
    assert metrics.media_searches == {"fixture": 1}
    assert metrics.media_funnel == {
        "normalized_returned": 6, "unique_considered": 3,
        "hard_rejected": 1, "duplicates": 1, "eligible": 2,
        "budget_unexamined": 2, "score_rejected": 1,
        "above_threshold": 1, "selected": 1, "used_real": 1,
    }
    assert metrics.media_assets_rejected == 2
    assert sum(metrics.media_rejections.values()) == 2
    assert metrics.media_rights_blocked == 1
    assert metrics.media_downloads == 1
    assert scenes[0]["asset"]["asset_id"] == "good"
    media = metrics.to_dict({"media": scenes}, {}, "metrics")["consumption"]["media"]
    assert media["funnel"] == metrics.media_funnel
    assert media["rejection_reasons"] == metrics.media_rejections


def test_synthetic_percentage_counts_generated_assets_not_scene_type():
    metrics = RunMetrics("fixture", "receipt", "ai")
    metrics.media_record_visual_type("historical_art")
    metrics.media_record_fallback("card")
    metrics.media_synth_diagrams = 1
    assert metrics.media_visual_report(1)["gerado_por_codigo_pct"] == 100.0


def test_unsplash_jpg_transform_is_not_rejected_for_missing_extension():
    from curio.stages import media_rules
    asset = MediaAsset(provider="unsplash", asset_id="photo", title="receipt",
                       download_url="https://images.unsplash.com/photo-123?w=1920&q=80&fm=jpg",
                       license="Licença Unsplash (uso livre)", width=1600, height=1600)
    assert visual._validate_asset_for(asset, []) == ""
    assert visual._validate_asset(asset)
    assert media_rules.passes_hard_filters(asset.to_dict(), []) == ""
    for url in ("https://example.test/page?fm=jpg",
                "https://images.unsplash.com/photo-123?fm=html",
                "https://images.unsplash.com/photo-123",
                "https://images.unsplash.com.evil.test/photo-123?fm=jpg"):
        asset.download_url = url
        assert visual._validate_asset_for(asset, []) == "não é imagem (jpg/png/webp)"
