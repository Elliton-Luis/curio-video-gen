"""Media acquisition, manual-media standby and source labels."""

from __future__ import annotations

import os
import sys

from . import ffmpeg as ff
from . import textnorm
from .config import CurioConfig
from .media import download_asset, get_providers
from .media.providers import MediaAsset, MediaError, classify_rights
from .stages.scenes import Chapter

MANUAL_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


class MediaStandby(RuntimeError):
    """No image exists; project waits for manual images."""

    def __init__(self, slug: str, manual_dir: str, n_scenes: int):
        self.slug = slug
        self.manual_dir = manual_dir
        self.n_scenes = n_scenes
        super().__init__(
            f"projeto '{slug}' em STANDBY: nenhuma imagem encontrada para "
            f"{n_scenes} cena(s). Coloque fotos (.jpg/.png/.webp) em "
            f"{manual_dir} e rode o generate de novo para continuar o vídeo."
        )


def _relevance(query: str, asset: MediaAsset) -> int:
    title = asset.title.lower()
    return sum(1 for term in textnorm.query_terms(query) if term in title)


def fetch_media(chapters: list[Chapter], cfg: CurioConfig,
                metrics=None) -> tuple[list[dict], list[str]]:
    """Fetch one relevant asset per scene; report failure for fallback."""
    providers = get_providers(cfg)
    search_memo: dict[tuple[str, str], list[MediaAsset]] = {}
    scenes, warnings = [], []
    for chapter in chapters:
        ranked: list[tuple[int, str, MediaAsset]] = []
        seen = set()
        for query in chapter.visual_queries:
            for provider in providers:
                memo_key = (provider.name, query)
                if memo_key not in search_memo:
                    try:
                        search_memo[memo_key] = provider.search(query, metrics=metrics)
                    except MediaError as exc:
                        print(f"AVISO: {exc} — tentando próxima fonte.",
                              file=sys.stderr)
                        search_memo[memo_key] = []
                for candidate in search_memo[memo_key]:
                    if candidate.asset_id in seen:
                        continue
                    seen.add(candidate.asset_id)
                    ranked.append((_relevance(query, candidate), query, candidate))
        ranked.sort(key=lambda item: -item[0])
        ranked = [item for item in ranked if item[0] > 0]
        blocked = [item for item in ranked
                   if classify_rights(item[2].license or "", item[2].provider)
                   == "blocked"]
        for _score, _query, candidate in blocked:
            message = (f"cena {chapter.id}: '{candidate.title[:50]}' descartado — "
                       f"licença bloqueada ({candidate.license or 'sem licença'})")
            warnings.append(message)
            print(f"AVISO: {message}", file=sys.stderr)
        ranked = [item for item in ranked
                  if classify_rights(item[2].license or "", item[2].provider)
                  != "blocked"]
        asset = None
        for _score, _query, candidate in ranked:
            try:
                asset = download_asset(candidate, cfg.cache_dir, metrics)
                break
            except MediaError as exc:
                print(f"AVISO: {exc} — tentando próximo asset.", file=sys.stderr)
        if asset is None:
            message = (f"cena {chapter.id}: sem mídia relevante "
                       f"({', '.join(chapter.visual_queries) or 'sem consultas'}) — fallback")
            warnings.append(message)
            print(f"AVISO: {message}", file=sys.stderr)
        scenes.append({"chapter_id": chapter.id,
                       "asset": asset.to_dict() if asset else None,
                       "reused_from": None})
    _resolve_reuse(scenes)
    return scenes, warnings


def _resolve_reuse(scenes: list[dict]) -> None:
    """Reuse nearest own image for scenes without selected media."""
    have = [scene for scene in scenes if scene["asset"]]
    if not have:
        return
    for scene in scenes:
        if scene["asset"] is not None:
            continue
        cid = scene["chapter_id"]
        nearest = min(have, key=lambda item: (abs(item["chapter_id"] - cid),
                                             0 if item["chapter_id"] < cid else 1))
        scene["asset"] = nearest["asset"]
        scene["reused_from"] = nearest["chapter_id"]
        print(f"AVISO: cena {cid} reusa imagem da cena "
              f"{nearest['chapter_id']} (sem mídia própria).", file=sys.stderr)


def manual_media_dir(paths) -> str:
    return os.path.join(paths.root, "assets", "manual")


def write_manual_readme(manual_dir: str, slug: str, n_scenes: int) -> None:
    os.makedirs(manual_dir, exist_ok=True)
    readme = os.path.join(manual_dir, "COMO_USAR.txt")
    if os.path.isfile(readme):
        return
    with open(readme, "w", encoding="utf-8") as fh:
        fh.write(
            f"Projeto '{slug}' em STANDBY: nenhuma imagem automática.\n"
            f"1) Coloque fotos aqui (.jpg/.jpeg/.png/.webp) — "
            f"ideal: 1 por cena ({n_scenes} cenas).\n"
            "2) Nomes em ordem alfabética definem a ordem das cenas "
            "(ex.: 01-abertura.jpg, 02-meio.jpg).\n"
            "3) Rode o generate de novo (sem --force) para continuar.\n"
            "Com menos fotos que cenas, as fotos rodiziam entre as cenas.\n")


def _probe_image_dims(path: str) -> tuple[int, int]:
    try:
        proc = ff.run([ff.FFPROBE, "-v", "error", "-select_streams", "v:0",
                       "-show_entries", "stream=width,height", "-of", "csv=p=0", path])
        if proc.returncode == 0:
            width, height = proc.stdout.strip().split(",")[:2]
            return int(width), int(height)
    except (OSError, ValueError):
        pass
    return 0, 0


def manual_media_scenes(chapters: list[Chapter], manual_dir: str) -> list[dict] | None:
    """Build scene media from sorted user files; None means no files."""
    if not os.path.isdir(manual_dir):
        return None
    files = sorted(name for name in os.listdir(manual_dir)
                   if name.lower().endswith(MANUAL_IMAGE_EXTS)
                   and os.path.isfile(os.path.join(manual_dir, name)))
    if not files:
        return None
    scenes = []
    for index, chapter in enumerate(chapters):
        name = files[index % len(files)]
        donor = chapters[index % len(files)].id
        local = os.path.join(manual_dir, name)
        stem = os.path.splitext(name)[0]
        width, height = _probe_image_dims(local)
        asset = {"provider": "manual", "asset_id": f"manual-{stem}",
                 "title": stem.replace("-", " ").replace("_", " "),
                 "author": "", "license": "manual do usuário", "license_url": "",
                 "source_url": "", "download_url": "", "download_fallback_url": "",
                 "width": width, "height": height, "size_bytes": os.path.getsize(local),
                 "kind": "image", "local_path": local, "used_in": f"cena {chapter.id}"}
        scenes.append({"chapter_id": chapter.id, "asset": asset,
                       "assets": [{"asset": asset, "query": "manual",
                                   "relevance": 100, "order": 0}],
                       "reused_from": None if donor == chapter.id else donor})
    return scenes


def scene_label(chapter: Chapter) -> str:
    parts = [str(getattr(chapter, "subject", "") or "").strip()]
    parts = [part for part in parts if part]
    entities = [str(item).strip() for item in
                (getattr(chapter, "visual_entities", []) or []) if str(item).strip()]
    if not parts and entities:
        parts = entities[:2]
    return f"cena {chapter.id}" if not parts else \
        f"cena {chapter.id} · " + " / ".join(parts)[:70]


def count_assets(media_scenes: list[dict]) -> int:
    count = 0
    for scene in media_scenes or []:
        if scene.get("asset") is not None:
            count += 1
        elif any((entry.get("asset") or {}).get("local_path")
                 for entry in scene.get("assets") or []):
            count += 1
    return count
