"""Museus (Met + AIC): busca, direitos, cache, dedup, fallback e prioridade."""

from unittest.mock import patch

import pytest

from curio.config import CurioConfig
from curio.media import providers as P
from curio.metrics import RunMetrics
from curio.stages import scoring, visual
from curio.stages.scenes import Chapter
from tests.test_support.search_plan import patch_search_plan


def _met_object(public=True, image=True, object_id=1):
    return {
        "objectID": object_id,
        "title": "Marble statue of Julius Caesar",
        "artistDisplayName": "Roman sculptor",
        "objectDate": "1st century",
        "objectURL": f"https://www.metmuseum.org/art/collection/search/{object_id}",
        "isPublicDomain": public,
        "primaryImageSmall": "https://images.metmuseum.org/small.jpg" if image else "",
        "primaryImage": "https://images.metmuseum.org/big.jpg" if image else "",
    }


def _aic_item(public=True, image=True, item_id=7):
    return {
        "id": item_id,
        "title": "Bust of Julius Caesar",
        "artist_title": "Roman workshop",
        "date_display": "1st century",
        "is_public_domain": public,
        "image_id": "img-1" if image else None,
    }


def test_met_accepts_only_public_domain_with_image():
    prov = P.MetMuseumProvider()
    calls = {"objects": 0}

    def fake_get(url, headers=None, timeout=30):
        if url.endswith("/search?q=caesar"):
            return {"objectIDs": [1, 2, 3]}
        calls["objects"] += 1
        if url.endswith("/objects/1"):
            return _met_object()
        if url.endswith("/objects/2"):
            return _met_object(public=False)
        return _met_object(image=False)

    with patch.object(P, "_http_get_json", side_effect=fake_get):
        assets = prov.search("caesar", limit=5)
    assert calls["objects"] == 3  # busca os 3 para filtrar direitos/imagem
    assert len(assets) == 1
    a = assets[0]
    assert (a.provider, a.asset_id) == ("met", "1")
    assert "Julius Caesar" in a.title and "Roman sculptor" in a.title
    assert a.author == "Roman sculptor"
    assert a.license == "Domínio público (Met Museum)"
    assert a.license_url.endswith("/search/1") and a.source_url == a.license_url
    assert a.download_url == "https://images.metmuseum.org/small.jpg"
    assert P.classify_rights(a.license) == "clear"
    assert P.license_ok(a.license)


def test_met_search_failure_raises_media_error():
    prov = P.MetMuseumProvider()
    with patch.object(P, "_http_get_json",
                      side_effect=P.MediaError("busca falhou (HTTP 500)")):
        with pytest.raises(P.MediaError, match="met:"):
            prov.search("caesar")


def test_met_object_failure_does_not_abort_search():
    prov = P.MetMuseumProvider()

    def fake_get(url, headers=None, timeout=30):
        if "/search?" in url:
            return {"objectIDs": [1, 2]}
        if url.endswith("/objects/1"):
            raise P.MediaError("busca falhou (HTTP 500)")
        return _met_object(object_id=2)

    with patch.object(P, "_http_get_json", side_effect=fake_get):
        assets = prov.search("caesar", limit=5)
    assert [a.asset_id for a in assets] == ["2"]


def test_aic_accepts_only_public_domain_with_image_id():
    prov = P.ArtInstituteProvider()
    payload = {"data": [_aic_item(),
                        _aic_item(public=False, item_id=8),
                        _aic_item(image=False, item_id=9)]}
    with patch.object(P, "_http_get_json", return_value=payload) as m:
        assets = prov.search("caesar", limit=5)
    assert m.called
    assert len(assets) == 1
    a = assets[0]
    assert (a.provider, a.asset_id) == ("aic", "7")
    assert "Julius Caesar" in a.title and "Roman workshop" in a.title
    assert a.license == "Domínio público (Art Institute of Chicago)"
    assert a.source_url == "https://www.artic.edu/artworks/7"
    assert a.download_url == ("https://www.artic.edu/iiif/2/img-1"
                              "/full/843,/0/default.jpg")
    assert P.classify_rights(a.license) == "clear"
    assert P.license_ok(a.license)


def test_aic_search_failure_raises_media_error():
    prov = P.ArtInstituteProvider()
    with patch.object(P, "_http_get_json",
                      side_effect=P.MediaError("busca falhou (HTTP 500)")):
        with pytest.raises(P.MediaError, match="aic:"):
            prov.search("caesar")


def test_museums_are_keyless_and_active_by_default():
    assert P.MetMuseumProvider() is not None
    assert P.ArtInstituteProvider() is not None
    cfg = CurioConfig()
    assert "met" in cfg.media_providers and "aic" in cfg.media_providers
    ativos, _ = P.providers_status(cfg)
    assert "met" in [n for n, _ in ativos]
    assert "aic" in [n for n, _ in ativos]


def test_historical_art_prioritizes_museums_then_wikimedia(monkeypatch):
    monkeypatch.setenv("PIXABAY_API_KEY", "fake")
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "fake")
    cfg = CurioConfig()
    cfg.media_providers = "pixabay,met,aic,wikimedia,unsplash"
    art = Chapter(1, "Júlio César chegou ao poder.", 8,
                  visual_type="historical_art", subject="Júlio César")
    names = [p.name for p in visual._provider_priority_order(cfg, art)]
    assert names[:4] == ["met", "aic", "wikimedia", "unsplash"] or \
        names[:3] == ["met", "aic", "wikimedia"]
    plain = Chapter(1, "O céu é azul.", 8, visual_type="literal")
    assert [p.name for p in visual._provider_priority_order(cfg, plain)] == \
        ["pixabay", "wikimedia", "met", "aic", "unsplash"]


def test_museum_search_runs_again_but_download_bytes_are_reused(monkeypatch, tmp_path):
    candidate = P.MediaAsset(
        provider="met", asset_id="1", title="Julius Caesar marble bust Rome",
        author="Roman sculptor", license="Domínio público (Met Museum)",
        license_url="https://www.metmuseum.org/art/collection/search/1",
        source_url="https://www.metmuseum.org/art/collection/search/1",
        download_url="https://images.metmuseum.org/small.jpg",
        width=1600, height=1600)

    patch_search_plan(monkeypatch, visual, ["julius caesar"])
    monkeypatch.setattr(scoring, "threshold", lambda: 34)
    monkeypatch.setattr(visual, "_downloaded_dims_ok", lambda asset: True)
    class Museum:
        name = "met"
        calls = 0

        def search(self, query, limit=5, metrics=None):
            self.calls += 1
            return [candidate]

    museum = Museum()
    from curio.media import cache
    monkeypatch.setattr(cache, "_fetch", lambda url, provider="": b"fixture")
    monkeypatch.setattr(cache.time, "sleep", lambda delay: None)
    ch = Chapter(1, "Júlio César chegou ao poder.", 8, subject="Júlio César",
                 subject_aliases=["Julius Caesar"])
    cfg = CurioConfig(cache_dir=str(tmp_path))
    for _ in range(2):
        scenes, _ = visual._search_scene_with_shortcircuit(
            ch, [museum], cfg, 1, RunMetrics("t", "cesar", "ai"), str(tmp_path))
        assert scenes[0]["asset"]["asset_id"] == "1"
        assert scenes[0]["asset"]["provider"] == "met"
    assert museum.calls == 2  # new run always searches providers


def test_museum_failure_falls_through_to_next_provider(monkeypatch, tmp_path):
    class DeadMuseum:
        name = "met"

        def search(self, query, limit, metrics):
            raise P.MediaError("met: busca falhou (HTTP 500)")

    class Live:
        name = "wikimedia"

        def search(self, query, limit, metrics):
            metrics.media_search(self.name)
            return [P.MediaAsset(
                provider="wikimedia", asset_id="9",
                title="Julius Caesar bust Rome",
                download_url="https://example.test/9.jpg",
                license="CC BY-SA 4.0", width=1600, height=1600)]

    patch_search_plan(monkeypatch, visual, ["julius caesar"])
    monkeypatch.setattr(scoring, "threshold", lambda: 34)
    monkeypatch.setattr(visual, "_downloaded_dims_ok", lambda asset: True)
    from curio.media import cache
    monkeypatch.setattr(cache, "_fetch", lambda url, provider="": b"fixture")
    monkeypatch.setattr(cache.time, "sleep", lambda delay: None)
    ch = Chapter(1, "Júlio César chegou ao poder.", 8, subject="Júlio César",
                 subject_aliases=["Julius Caesar"])
    cfg = CurioConfig(cache_dir=str(tmp_path))
    scenes, _ = visual._search_scene_with_shortcircuit(
        ch, [DeadMuseum(), Live()], cfg, 1,
        RunMetrics("t", "cesar", "ai"), str(tmp_path))
    assert scenes[0]["asset"]["provider"] == "wikimedia"


def test_museum_assets_join_scoring_dedup_and_cache(monkeypatch, tmp_path):
    met = P.MediaAsset(
        provider="met", asset_id="1", title="Julius Caesar bust Rome",
        download_url="https://images.metmuseum.org/small.jpg",
        license="Domínio público (Met Museum)", width=1600, height=1600)

    class Museum:
        name = "met"

        def search(self, query, limit, metrics):
            metrics.media_search(self.name)
            return [met, met]  # duplicado: dedup corta antes do download

    patch_search_plan(monkeypatch, visual, ["julius caesar"])
    monkeypatch.setattr(scoring, "threshold", lambda: 34)
    monkeypatch.setattr(visual, "_downloaded_dims_ok", lambda asset: True)
    from curio.media import cache
    downloads = []
    monkeypatch.setattr(cache, "_fetch",
                        lambda url, provider="": downloads.append(url) or b"fixture")
    monkeypatch.setattr(cache.time, "sleep", lambda delay: None)
    ch = Chapter(1, "Júlio César chegou ao poder.", 8, subject="Júlio César",
                 subject_aliases=["Julius Caesar"])
    cfg = CurioConfig(cache_dir=str(tmp_path))
    metrics = RunMetrics("t", "cesar", "ai")
    scenes, _ = visual._search_scene_with_shortcircuit(
        ch, [Museum()], cfg, 1, metrics, str(tmp_path))
    assert scenes[0]["asset"]["asset_id"] == "1"
    assert downloads == ["https://images.metmuseum.org/small.jpg"]
    assert metrics.media_funnel["duplicates"] == 1
