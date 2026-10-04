"""Identity and manifest for a project's editorial media selection cache."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass


SCHEMA_VERSION = 1
SELECTION_POLICY_VERSION = 2


@dataclass(frozen=True)
class MediaSelectionManifest:
    schema_version: int
    policy_version: int
    input_signature: str
    scene_ids: tuple[int, ...]
    asset_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "input_signature": self.input_signature,
            "scene_ids": list(self.scene_ids),
            "asset_ids": list(self.asset_ids),
        }

    @classmethod
    def from_dict(cls, value: dict) -> "MediaSelectionManifest":
        return cls(
            schema_version=int(value["schema_version"]),
            policy_version=int(value["policy_version"]),
            input_signature=str(value["input_signature"]),
            scene_ids=tuple(int(item) for item in value["scene_ids"]),
            asset_ids=tuple(str(item) for item in value["asset_ids"]),
        )

    def matches(self, signature: str, scene_ids: list[int]) -> bool:
        return (self.schema_version == SCHEMA_VERSION
                and self.policy_version == SELECTION_POLICY_VERSION
                and self.input_signature == signature
                and self.scene_ids == tuple(scene_ids))


def media_selection_signature(chapters, genre: str, max_images: int,
                              providers: list[str], min_score: float) -> str:
    """Fingerprint only inputs that can affect acquisition or selection.

    Render timing is deliberately absent: changing a duration must not cause
    another search. The explicit policy version invalidates decisions when
    editorial selection rules change.
    """
    semantic_fields = (
        "narration", "planning_mode", "visual_intent", "visual_intent_structured",
        "visual_type", "subject", "subject_aliases", "visual_entities",
        "context", "forbidden", "video_context", "primary_entity", "event",
        "place", "period", "representations", "visual_queries",
        "global_visual_queries",
    )
    scenes = []
    for chapter in chapters:
        raw = chapter.to_dict()
        scenes.append({"id": chapter.id,
                       **{key: raw.get(key) for key in semantic_fields}})
    payload = {
        "schema_version": SCHEMA_VERSION,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "genre": genre,
        "max_images": max(1, min(5, int(max_images))),
        "providers": list(providers),
        "min_score": float(min_score),
        "scenes": scenes,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_manifest(path: str, media_scenes: list[dict], signature: str) -> None:
    manifest = MediaSelectionManifest(
        schema_version=SCHEMA_VERSION,
        policy_version=SELECTION_POLICY_VERSION,
        input_signature=signature,
        scene_ids=tuple(int(scene["chapter_id"]) for scene in media_scenes),
        asset_ids=tuple(str((scene.get("asset") or {}).get("asset_id") or "")
                        for scene in media_scenes),
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(manifest.to_dict(), fh, ensure_ascii=False, indent=1)
    os.replace(temporary, path)


def read_manifest(path: str) -> MediaSelectionManifest | None:
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
        return MediaSelectionManifest.from_dict(value)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def selection_cache_is_current(media_scenes: list[dict], manifest_path: str,
                               signature: str,
                               scene_ids: list[int]) -> bool:
    """Accept a selection only when inputs match, or it is explicitly manual."""
    manifest = read_manifest(manifest_path)
    if manifest and manifest.matches(signature, scene_ids):
        return True
    selected_assets = [asset for scene in media_scenes
                       for asset in ([scene.get("asset")]
                                     + [entry.get("asset") for entry in
                                        scene.get("assets", [])])
                       if asset]
    return bool(selected_assets) and all(
        asset.get("provider") == "manual" for asset in selected_assets)
