"""Planejamento de imagens, inserções, motion e SFX por cena.

Busca de mídia termina em `visual.py`. Este módulo transforma assets já
selecionados em planos renderizáveis. Não busca, não baixa e não chama LLM.
"""

from __future__ import annotations

import random

from .. import textnorm
from ..config import ENTRY_STYLES
from .scene_contract import SemanticScene, TimelineSpan
from .visual_beats import asset_key, bind_assets, plan as plan_visual_beats

LEGACY_STYLES = ("fade_scale",)
SFX_EVERY = 3
SFX_KINDS = ("swish", "tap")
SFX_GAIN_DB = -22
SFX_DURATION = 0.35
INSERT_SFX_KIND = "tap"
INSERT_SFX_DURATION = 0.4
ROTATIONS_DEG = (-5.0, 4.0, -3.0, 6.0, -4.0)
OFFSET_DX = (0, -34, 30, -22, 26)
OFFSET_DY = (0, -24, 18, 26, -18)
CARD_WIDTH_RATIO = 0.85
MIN_IMAGE_SECONDS = 1.0


def insertion_scenes(n_scenes: int, budget: int) -> set[int]:
    """Choose evenly spaced interior scenes for video-level insertions."""
    if budget <= 0 or n_scenes < 2:
        return set()
    budget = min(budget, n_scenes - 1)
    inner = list(range(1, n_scenes - 1))
    slots = len(inner)
    if slots <= 0:
        return set()
    positions: list[int] = []
    for k in range(1, budget + 1):
        pos = min(slots - 1, max(0, round((k - 0.5) * slots / budget)))
        while pos in positions and pos + 1 < slots:
            pos += 1
        if pos in positions:
            pos = min(positions) - 1 if min(positions) > 0 else 0
            while pos in positions and pos > 0:
                pos -= 1
        if pos not in positions:
            positions.append(pos)
    return {inner[p] for p in positions}


def _topic_terms(scene: SemanticScene) -> set[str]:
    if not isinstance(scene, SemanticScene):
        raise TypeError("visual insertion ordering requires SemanticScene")
    terms: set[str] = set()
    # Timeline may refine ordering only from the already approved visual
    # search plan. It must not invent relevance from narration or rebuild
    # aliases/context during render.
    semantic_terms = [
        *(rep.query for rep in scene.representations),
    ]
    for query in semantic_terms:
        if not str(query or "").strip():
            continue
        terms.update(textnorm.query_terms(query))
        for word in query.replace(",", " ").split():
            base = textnorm.fold(word)
            if len(base) >= 3 and base not in textnorm.VISUAL_STOP_PT:
                terms.add(base)
    return terms


def _topic_score(asset: dict, terms: set[str]) -> int:
    title = textnorm.fold(str(asset.get("title", "") or ""))
    return sum(1 for term in terms if term in title) if title else 0


def order_for_insertion(entries: list, scene: SemanticScene) -> tuple[list, list]:
    """Split (background, insertion); insertion must improve specificity."""
    if len(entries) < 2:
        return list(entries), []
    terms = _topic_terms(scene)
    if not terms:
        return [entries[0]], []
    scored = sorted(((_topic_score(e.get("asset") or {}, terms), i, e)
                     for i, e in enumerate(entries)),
                    key=lambda item: (-item[0], item[1]))
    best_score, _, insertion = scored[0]
    if best_score <= 0:
        return [entries[0]], []
    lower = [item for item in scored[1:] if item[0] < best_score]
    if not lower:
        return [entries[0]], []
    return [lower[0][2]], [insertion]


def _overlap_for(duration: float, n: int, cap: float) -> float:
    if n <= 1:
        return 0.0
    return max(0.4, min(cap, duration * 0.15))


def plan_scene_images(duration: float, n: int, overlap_cap: float = 0.9,
                      styles: tuple = ENTRY_STYLES, start: int = 0) -> list[dict]:
    """Plan image times and album-card motion for one scene."""
    duration = max(0.5, float(duration))
    while n > 1 and duration / n < MIN_IMAGE_SECONDS:
        n -= 1
    if n <= 1:
        return []
    overlap = _overlap_for(duration, n, overlap_cap)
    step = duration / n
    base_entry = min(0.9, max(0.4, step * 0.3))
    plan = []
    for i in range(n):
        start_t = round(i * step, 3)
        dur = round(duration - start_t if i == n - 1 else step + overlap, 3)
        transition = "base" if i == 0 else styles[(start + i - 1) % len(styles)]
        entry_dur = (0.0 if i == 0 else
                     round(base_entry + ((start + i) % 3) * 0.05, 3))
        plan.append({
            "order": i, "start": start_t, "duration": dur,
            "transition": transition,
            "scale": 1.0 if i == 0 else CARD_WIDTH_RATIO,
            "rotation_deg": 0.0 if i == 0 else ROTATIONS_DEG[i % len(ROTATIONS_DEG)],
            "dx": 0 if i == 0 else OFFSET_DX[i % len(OFFSET_DX)],
            "dy": 0 if i == 0 else OFFSET_DY[i % len(OFFSET_DY)],
            "entry_dur": entry_dur,
        })
    return plan


def _spec_images(entries: list[dict], duration: float,
                 overlap_cap: float = 0.9,
                 styles: tuple = ENTRY_STYLES,
                 start: int = 0) -> tuple[list[dict], int]:
    """Build render-ready images from selected entries."""
    duration = max(0.5, float(duration))
    if len(entries) == 1:
        entry = entries[0]
        asset = entry.get("asset") or {}
        return [{
            "order": 0, "query": entry.get("query", ""),
            "asset_id": asset.get("asset_id", ""), "title": asset.get("title", ""),
            "provider": asset.get("provider", ""), "author": asset.get("author", ""),
            "license": asset.get("license", ""), "source_url": asset.get("source_url", ""),
            "local_path": asset.get("local_path", ""), "kind": asset.get("kind", "image"),
            "start": 0.0, "duration": round(duration, 3), "transition": "base",
            "scale": 1.0, "rotation_deg": 0.0, "dx": 0, "dy": 0,
            "entry_dur": 0.0, "sfx": None,
        }], 0
    plan = plan_scene_images(duration, len(entries), overlap_cap, styles, start)
    if not plan and entries:
        return _spec_images(entries[:1], duration, overlap_cap, styles, start)
    images = []
    for spec, entry in zip(plan, entries):
        asset = entry.get("asset") or {}
        images.append({
            "order": spec["order"], "query": entry.get("query", ""),
            "asset_id": asset.get("asset_id", ""), "title": asset.get("title", ""),
            "provider": asset.get("provider", ""), "author": asset.get("author", ""),
            "license": asset.get("license", ""), "source_url": asset.get("source_url", ""),
            "local_path": asset.get("local_path", ""), "kind": asset.get("kind", "image"),
            "start": spec["start"], "duration": spec["duration"],
            "transition": spec["transition"], "scale": spec["scale"],
            "rotation_deg": spec["rotation_deg"], "dx": spec["dx"],
            "dy": spec["dy"], "entry_dur": spec["entry_dur"], "sfx": None,
        })
    return images, sum(1 for image in images if image["order"] > 0)


def _shuffled_styles(seed: str) -> list[str]:
    order = list(ENTRY_STYLES)
    random.Random(seed or "curio").shuffle(order)
    return order


def _assign_sfx(images: list[dict], scene_start: float,
                overlay_counter: int, sfx_ordinal: int,
                enabled: bool) -> tuple[int, int]:
    for image in images:
        if image["order"] == 0:
            image["sfx"] = None
            continue
        if enabled and overlay_counter % SFX_EVERY == 0:
            image["sfx"] = {
                "kind": SFX_KINDS[sfx_ordinal % len(SFX_KINDS)],
                "at": round(scene_start + image["start"], 3),
                "gain_db": SFX_GAIN_DB, "duration": SFX_DURATION,
            }
            sfx_ordinal += 1
        else:
            image["sfx"] = None
        overlay_counter += 1
    return overlay_counter, sfx_ordinal


def mark_insertion(images: list[dict], scene_start: float, style: str,
                   gain_db: int, sfx: bool) -> None:
    for image in images:
        if image.get("order", 0) == 0:
            continue
        image["transition"] = style
        image["sfx"] = ({"kind": INSERT_SFX_KIND,
                         "at": round(scene_start + image.get("start", 0.0), 3),
                         "gain_db": gain_db, "duration": INSERT_SFX_DURATION}
                        if sfx else None)


def retime_visual_timeline(visual_timeline: list[dict], timeline_spans) -> list[dict]:
    """Recalculate visual timestamps after audio timing changes."""
    scene_ids = tuple(scene["chapter_id"] for scene in visual_timeline)
    span_ids = tuple(span.scene_id for span in timeline_spans)
    if len(scene_ids) != len(set(scene_ids)) or scene_ids != span_ids:
        raise ValueError("visual timeline spans do not match scene order")
    times = {span.scene_id: (float(span.start), float(span.end))
             for span in timeline_spans}
    out = []
    for scene in visual_timeline:
        start, end = times.get(scene["chapter_id"], (scene["start"], scene["end"]))
        duration = max(0.5, end - start)
        old = {image["order"]: image for image in scene["images"]}
        entries = [{"query": image.get("query", ""),
                    "asset": {key: image.get(key, "") for key in
                              ("asset_id", "title", "provider", "author", "license",
                               "source_url", "download_url", "local_path", "kind")}}
                   for image in scene["images"]]
        images, _used = _spec_images(entries, duration)
        for image in images:
            previous = old.get(image["order"], {})
            if previous.get("transition") not in (None, "base"):
                image["transition"] = previous["transition"]
            sfx = previous.get("sfx")
            image["sfx"] = ({**sfx, "at": round(start + image["start"], 3)}
                            if image["order"] > 0 and isinstance(sfx, dict) else None)
        scene = dict(scene)
        beats = plan_visual_beats(duration, start)
        backgrounds = bind_assets(beats, scene.get("backgrounds") or images[:1], start)
        for beat in beats:
            beat.setdefault("asset_ids", [])
            for image in images[1:]:
                key = asset_key(image)
                if image["start"] < beat["end"] - start and key not in beat["asset_ids"]:
                    beat["asset_ids"].append(key)
        scene.update(start=round(start, 3), end=round(end, 3), images=images,
                     visual_beats=beats, backgrounds=backgrounds,
                     fallback=not images and not backgrounds)
        out.append(scene)
    return out


def visual_summary(visual_timeline: list[dict]) -> str:
    parts = []
    for scene in visual_timeline:
        if scene["fallback"]:
            parts.append(f"cena {scene['chapter_id']}: fallback")
            continue
        transitions = ",".join(image["transition"] for image in scene["images"][1:])
        sfx_count = sum(1 for image in scene["images"] if image.get("sfx"))
        parts.append(f"cena {scene['chapter_id']}: {len(scene['images'])} img"
                     + (f" [{transitions}]" if transitions else " [base]")
                     + (f" +{sfx_count}sfx" if sfx_count else "")
                     + (f"; {len(scene['backgrounds'])} fundos alternados"
                        if len(scene.get("backgrounds") or []) > 1 else ""))
    return "; ".join(parts)



def build_visual_timeline(semantic_scenes: tuple[SemanticScene, ...],
                          timeline_spans: tuple[TimelineSpan, ...],
                          media_scenes: list[dict],
                          overlap_cap: float = 0.9, seed: str = "",
                          sfx: bool = True,
                          insertions: int | None = None,
                          insert_style: str = "drop_in",
                           insert_gain_db: int = -15,
                          honor_order: bool = False) -> list[dict]:
    """Timeline visual renderizável: um trecho por cena com suas imagens.

    Cada trecho carrega texto/narração original, início/fim, imagens em
    ordem (com consulta que a encontrou), duração, transição e geometria
    de sobreposição. Cenas semânticas e spans alinhados são entradas
    separadas; os spans precisam ter tempos definidos antes desta chamada.

    `insertions` é o orçamento de fotos COMPLEMENTARES do VÍDEO inteiro
    (padrão 2, `None` mantém o álbum por cena sem limite). As cenas
    escolhidas por `insertion_scenes` recebem 1 cartaz a mais, sempre com
    `insert_style` (padrão: caiu do álbum) e um toque de som discreto no
    instante exato da entrada — as outras cenas ficam só com o fundo.

    `honor_order` respeita a ordem que já está em `assets` em vez de
    redecidir o papel de cada foto. É o que o `swap` precisa: se o
    replanejamento re-executasse `order_for_insertion`, ele devolveria a
    foto que o autor acabou de tirar para o fim.
    """
    _validate_visual_timeline_inputs(semantic_scenes, timeline_spans)
    by_chapter = {s["chapter_id"]: s for s in media_scenes}
    styles = _shuffled_styles(seed)
    sparse = insertions is not None and not honor_order
    insert_at = (insertion_scenes(len(semantic_scenes), insertions or 0)
                 if sparse else set())
    scene_no_insert: set[int] = set()  # cena que ficou sem deepenho
    overlay_counter, sfx_ordinal, style_pos = 0, 0, 0
    timeline = []
    background_uses: dict[str, int] = {}
    for idx, (scene_plan, span) in enumerate(zip(semantic_scenes, timeline_spans)):
        scene = by_chapter.get(scene_plan.id, {})
        start, end = round(float(span.start), 3), round(float(span.end), 3)
        dur = max(0.5, end - start)
        entries = list(scene.get("assets") or [])
        background_entries = list(entries)
        if not honor_order:
            background_entries.sort(key=lambda entry: (
                bool(entry.get("generic")),
                background_uses.get(asset_key(entry.get("asset") or {}), 0),
                -entry.get("score", 0)))
        if sparse:
            # A inserção tem de ser a imagem MAIS PRECISA sobre o assunto da
            # cena — é o que a diferencia do fundo. Sem candidata que bata o
            # fundo, a cena fica só com o fundo.
            background, insertion = order_for_insertion(entries, scene_plan)
            entries = background if idx not in insert_at else background + insertion
            if idx in insert_at and not insertion:
                scene_no_insert.add(scene_plan.id)
        images, consumed = _spec_images(entries, dur,
                                       overlap_cap, styles, style_pos)
        if sparse:
            # No modo esparso toda foto extra É uma inserção: entra no
            # ritmo de álbum e sempre marca com som, independentemente da
            # cadência ~1/3 do modo álbum cheio. `style_pos` não anda:
            # a sequência variada pertence só ao álbum cheio.
            mark_insertion(images, start, insert_style, insert_gain_db, sfx)
        else:
            style_pos += consumed
            overlay_counter, sfx_ordinal = _assign_sfx(
                images, start, overlay_counter, sfx_ordinal, sfx)
        beats = plan_visual_beats(dur, start)
        available = [_spec_images([entry], dur)[0][0] for entry in background_entries]
        backgrounds = bind_assets(beats, available, start)
        for background in backgrounds:
            key = asset_key(background)
            background_uses[key] = background_uses.get(key, 0) + 1
        for beat in beats:
            visible = beat.setdefault("asset_ids", [])
            for image in images[1:]:
                if image["start"] < beat["end"] - start:
                    key = asset_key(image)
                    if key and key not in visible:
                        visible.append(key)
        timeline.append({
            "chapter_id": scene_plan.id,
            "narration": scene_plan.narration,  # original, intocado
            "start": start,
            "end": end,
            "images": images,
            "visual_beats": beats,
            "backgrounds": backgrounds,
            "fallback": not images and not backgrounds,
            "reused_from": scene.get("reused_from"),
            **({"no_insertion": "nenhuma imagem mais precisa que o fundo"
               } if scene_plan.id in scene_no_insert else {}),
        })
    return timeline


def _validate_visual_timeline_inputs(semantic_scenes, timeline_spans) -> None:
    if (any(not isinstance(scene, SemanticScene) for scene in semantic_scenes)
            or any(not isinstance(span, TimelineSpan) for span in timeline_spans)):
        raise TypeError("visual timeline requires SemanticScene and TimelineSpan values")
    scene_ids = tuple(scene.id for scene in semantic_scenes)
    span_ids = tuple(span.scene_id for span in timeline_spans)
    if not scene_ids or len(scene_ids) != len(set(scene_ids)):
        raise ValueError("visual timeline requires unique semantic scenes")
    if scene_ids != span_ids:
        raise ValueError("visual timeline spans do not match scene order")

def rebuild_visual_timeline(semantic_scenes, timeline_spans,
                            media_scenes: list[dict], cfg,
                            seed: str = "") -> list[dict]:
    """Replan geometry from canonical scene and timing contracts."""
    return build_visual_timeline(
        semantic_scenes, timeline_spans, media_scenes,
        overlap_cap=float(cfg.visual_overlap), seed=seed,
        sfx=bool(cfg.visual_sfx), honor_order=True)
