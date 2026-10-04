"""Record selected visual assets and derive attribution/rights notes."""

from __future__ import annotations

from dataclasses import dataclass

from .media.providers import classify_rights
from .stages import sources as sources_stage
from .stages.scene_contract import SemanticScene


@dataclass(frozen=True)
class MediaSourceResult:
    credits: tuple[str, ...]
    rights_notes: tuple[str, ...]


def record_selected_media(scenes: list[SemanticScene], selections: list[dict],
                          registry) -> MediaSourceResult:
    """Write provenance for downloaded assets and return editorial notices."""
    labels = {scene.id: _scene_label(scene) for scene in scenes}
    notes: list[str] = []
    credits: list[str] = []
    for selected in selections:
        scene_id = int(selected["chapter_id"])
        label = labels.get(scene_id, f"cena {scene_id}")
        for entry in selected.get("assets") or []:
            asset = entry.get("asset") or {}
            if not asset.get("local_path"):
                continue
            rights = asset.get("rights_status", "") or classify_rights(
                asset.get("license", ""), asset.get("provider", ""))
            asset["rights_status"] = rights
            title = sources_stage.media_record_title(
                scene_label=label, provider=asset.get("provider", ""),
                asset_id=asset.get("asset_id", ""),
                fallback=str(asset.get("title", ""))[:80])
            registry.add_media(
                title=title, origin_url=asset.get("source_url", ""),
                file_url=asset.get("download_url", ""),
                provider=asset.get("provider", ""),
                author=asset.get("author", ""),
                license=asset.get("license", ""),
                license_url=asset.get("license_url", ""),
                local_path=asset.get("local_path", ""),
                used_in=f"cena {scene_id}", rights_status=rights,
                query=entry.get("query", ""), scene=f"cena {scene_id}",
                asset_id=asset.get("asset_id", ""))
            _append_attribution(asset, scene_id, credits, notes)
            if rights == "verify":
                _append_unique(notes, (
                    f"Cena {scene_id}: '{asset.get('title', '')[:60]}' entrou no vídeo com "
                    f"licença a conferir ({asset.get('provider', '')}: "
                    f"{asset.get('license') or 'desconhecida'}) — confira em "
                    f"{asset.get('license_url') or asset.get('source_url') or 'sem link'}"))
    return MediaSourceResult(tuple(credits), tuple(notes))


def _scene_label(scene: SemanticScene) -> str:
    parts = [str(scene.subject or "").strip()]
    parts = [part for part in parts if part]
    entities = [str(item).strip() for item in scene.visual_entities
                if str(item).strip()]
    if not parts and entities:
        parts = entities[:2]
    return f"cena {scene.id}" if not parts else \
        f"cena {scene.id} · " + " / ".join(parts)[:70]


def _append_attribution(asset: dict, scene_id: int, credits: list[str],
                        notes: list[str]) -> None:
    license_text = asset.get("license", "")
    if not sources_stage.requires_attribution(license_text):
        return
    credit = sources_stage.credit_line(
        author=asset.get("author", ""), title=asset.get("title", ""),
        license_text=license_text, source_url=asset.get("source_url", ""),
        license_url=asset.get("license_url", ""))
    _append_unique(credits, credit)
    if not asset.get("author", "").strip():
        _append_unique(notes, (
            f"cena {scene_id}: '{asset.get('title', '')[:50]}' tem licença que exige "
            f"atribuição mas o acervo não informou o autor ({license_text}) — confira em "
            f"{asset.get('license_url') or asset.get('source_url') or 'sem link'}"))


def _append_unique(target: list[str], value: str) -> None:
    if value not in target:
        target.append(value)
