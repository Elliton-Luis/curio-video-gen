from curio.media.providers import MediaAsset
from curio.stages import media_acquisition


def test_downloaded_media_contract_records_cache_origin(tmp_path, monkeypatch):
    asset = MediaAsset(
        provider="wikimedia", asset_id="stable-id", title="A painting",
        download_url="https://example.test/image.jpg", license="CC BY 4.0")
    asset_dir = tmp_path / "media" / "wikimedia"
    asset_dir.mkdir(parents=True)
    (asset_dir / "stable-id.jpg").write_bytes(b"cached bytes")
    (asset_dir / "stable-id.jpg.json").write_text("{}")
    monkeypatch.setattr(media_acquisition, "download_asset", lambda *_args: asset)

    result = media_acquisition._download_with_origin(asset, str(tmp_path))

    assert result.asset is asset
    assert result.origin == "cache"


def test_downloaded_dimensions_reject_missing_file(tmp_path):
    asset = MediaAsset(provider="wikimedia", asset_id="missing", title="A painting",
                       local_path=str(tmp_path / "missing.jpg"))

    assert media_acquisition.downloaded_dimensions_valid(asset) is False
