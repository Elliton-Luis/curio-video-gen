"""Immutable metadata snapshot for provider and selected media assets."""

from __future__ import annotations

from dataclasses import dataclass

from .providers import MediaAsset


@dataclass(frozen=True)
class MediaAssetSnapshot:
    """Frozen asset facts at a stage boundary; bytes lifecycle stays mutable."""

    provider: str
    asset_id: str
    title: str = ""
    author: str = ""
    license: str = ""
    license_url: str = ""
    source_url: str = ""
    download_url: str = ""
    download_fallback_url: str = ""
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    kind: str = "image"
    local_path: str = ""
    used_in: str = ""
    rights_status: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    date_created: str = ""
    media_type: str = "image"

    @classmethod
    def from_media_asset(cls, asset: MediaAsset) -> "MediaAssetSnapshot":
        if not isinstance(asset, MediaAsset):
            raise TypeError("media asset snapshot requires MediaAsset")
        return cls(
            provider=asset.provider, asset_id=asset.asset_id,
            title=asset.title, author=asset.author, license=asset.license,
            license_url=asset.license_url, source_url=asset.source_url,
            download_url=asset.download_url,
            download_fallback_url=asset.download_fallback_url,
            width=asset.width, height=asset.height, size_bytes=asset.size_bytes,
            kind=asset.kind, local_path=asset.local_path, used_in=asset.used_in,
            rights_status=asset.rights_status, description=asset.description,
            tags=tuple(asset.tags), categories=tuple(asset.categories),
            date_created=asset.date_created, media_type=asset.media_type)

    @classmethod
    def from_dict(cls, value: object) -> "MediaAssetSnapshot":
        if not isinstance(value, dict):
            raise TypeError("media asset snapshot requires an object")
        return cls.from_media_asset(MediaAsset.from_dict(value))

    def __post_init__(self) -> None:
        for name in ("provider", "asset_id"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"media asset snapshot {name} must be text")
        for name in ("tags", "categories"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or any(
                    not isinstance(item, str) for item in value):
                raise TypeError(f"media asset snapshot {name} must be immutable text")

    def to_dict(self) -> dict:
        """Project the existing MediaAsset JSON schema."""
        return {
            "provider": self.provider, "asset_id": self.asset_id,
            "title": self.title, "author": self.author,
            "license": self.license, "license_url": self.license_url,
            "source_url": self.source_url, "download_url": self.download_url,
            "download_fallback_url": self.download_fallback_url,
            "width": self.width, "height": self.height,
            "size_bytes": self.size_bytes, "kind": self.kind,
            "local_path": self.local_path, "used_in": self.used_in,
            "rights_status": self.rights_status,
            "description": self.description, "tags": list(self.tags),
            "categories": list(self.categories),
            "date_created": self.date_created, "media_type": self.media_type,
        }
