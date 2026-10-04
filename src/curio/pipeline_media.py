"""Manual-media standby, fallback instructions and source labels."""

from __future__ import annotations

import os

from . import ffmpeg as ff
from .stages.scene_contract import SemanticScene

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


def manual_media_scenes(semantic_scenes: list[SemanticScene],
                        manual_dir: str) -> list[dict] | None:
    """Build scene media from sorted user files; None means no files."""
    if any(not isinstance(scene, SemanticScene) for scene in semantic_scenes):
        raise TypeError("manual media requires SemanticScene values")
    if not os.path.isdir(manual_dir):
        return None
    files = sorted(name for name in os.listdir(manual_dir)
                   if name.lower().endswith(MANUAL_IMAGE_EXTS)
                   and os.path.isfile(os.path.join(manual_dir, name)))
    if not files:
        return None
    scenes = []
    for index, scene in enumerate(semantic_scenes):
        name = files[index % len(files)]
        donor = semantic_scenes[index % len(files)].id
        local = os.path.join(manual_dir, name)
        stem = os.path.splitext(name)[0]
        width, height = _probe_image_dims(local)
        asset = {"provider": "manual", "asset_id": f"manual-{stem}",
                 "title": stem.replace("-", " ").replace("_", " "),
                 "author": "", "license": "manual do usuário", "license_url": "",
                 "source_url": "", "download_url": "", "download_fallback_url": "",
                 "width": width, "height": height, "size_bytes": os.path.getsize(local),
                 "kind": "image", "local_path": local, "used_in": f"cena {scene.id}"}
        scenes.append({"chapter_id": scene.id, "asset": asset,
                       "assets": [{"asset": asset, "query": "manual",
                                    "relevance": 100, "order": 0}],
                       "visual_decision": {
                           "topic": scene.video_context.topic,
                           "visual_intent": (scene.visual_intent_structured
                                             or scene.visual_intent),
                           "entities": list(scene.visual_entities),
                           "primary_entity": scene.primary_entity or scene.subject,
                           "representations": [rep.to_dict()
                                               for rep in scene.representations],
                           "queries": [], "providers_consulted": [],
                           "candidates": [{"title": asset["title"],
                               "provider": "manual", "decision": "selected",
                               "reason": "asset supplied by user"}],
                           "selected": {"title": asset["title"], "provider": "manual",
                                        "reason": "asset supplied by user"},
                           "fallback": "manual",
                       },
                       "reused_from": None if donor == scene.id else donor})
    return scenes


def count_assets(media_scenes: list[dict]) -> int:
    count = 0
    for scene in media_scenes or []:
        if scene.get("asset") is not None:
            count += 1
        elif any((entry.get("asset") or {}).get("local_path")
                 for entry in scene.get("assets") or []):
            count += 1
    return count
