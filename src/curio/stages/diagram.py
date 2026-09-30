"""Diagramas originais gerados por código (sem rede, sem licença de terceiros).

Cobre cenas de mecanismo que bancos de foto não explicam (ex.: tira de
teste com fluxo, ouro coloidal e linhas T/C): uma tira simples com o
líquido subindo, os pontos de ouro e as duas linhas aparecendo.
Determinístico por termo (seed = hash), cacheado em `cache/synth/`.
"""

from __future__ import annotations

import hashlib
import os
import random

STRIP_W, STRIP_H = 1200, 1600


def _labels(language: str) -> dict[str, str]:
    if str(language or "").lower().startswith("en"):
        return {
            "title": "HOW A TEST STRIP WORKS",
            "sample": "urine sample",
            "gold": "gold antibodies",
            "flow": "flow",
            "test": "TEST (T) — hCG present",
            "control": "CONTROL (C) — always",
            "legend_pos": "T + C  =  positive",
            "legend_neg": "C only  =  negative",
        }
    return {
        "title": "COMO A TIRA FUNCIONA",
        "sample": "amostra de urina",
        "gold": "anticorpos de ouro",
        "flow": "fluxo",
        "test": "TESTE (T) — hCG presente",
        "control": "CONTROLE (C) — sempre",
        "legend_pos": "T + C  =  positivo",
        "legend_neg": "só C  =  negativo",
    }


def _font(size: int):
    """DejaVu Bold do sistema; cai para a fonte padrão do PIL."""
    from PIL import ImageFont
    try:
        from .. import ffmpeg as ff
        path = ff.find_font_bold()
        if path and os.path.isfile(path):
            return ImageFont.truetype(path, size)
    except Exception:  # noqa: BLE001 — fonte nunca é fatal
        pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _key(terms: str, language: str) -> str:
    return hashlib.sha256(f"{language}|{terms}".lower().encode()).hexdigest()[:12]


def render_strip_diagram(terms: str, cache_dir: str,
                         language: str = "pt-BR"):
    """Desenha a tira de teste e retorna um MediaAsset pronto (`synth`).

    Reusa o PNG em cache quando os termos se repetem.
    """
    from ..media.providers import MediaAsset

    key = _key(terms or "test strip", language)
    out_dir = os.path.join(cache_dir, "synth")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"strip_{key}.png")
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 10000:
        return _asset(out_path, terms, language)

    from PIL import Image, ImageDraw

    lab = _labels(language)
    img = Image.new("RGB", (STRIP_W, STRIP_H), "#EDF1F7")
    d = ImageDraw.Draw(img)
    rng = random.Random(key)

    # Faixa de título
    d.rectangle([0, 0, STRIP_W, 130], fill="#1F3A5F")
    f_title = _font(46)
    d.text((STRIP_W // 2, 65), lab["title"], font=f_title,
           fill="white", anchor="mm")

    # Corpo da tira (cartão branco arredondado)
    x0, x1 = 330, 870
    d.rounded_rectangle([x0, 190, x1, 1330], radius=36, fill="white",
                        outline="#B9C4D4", width=4)
    cx = (x0 + x1) // 2

    # Amostra (base azul) + pad de ouro (pontos dourados determinísticos)
    d.rounded_rectangle([x0 + 24, 1180, x1 - 24, 1306], radius=18,
                        fill="#CFE3FA", outline="#7FA8DC", width=3)
    f_small = _font(27)
    d.text((cx, 1243), lab["sample"], font=f_small,
           fill="#1F3A5F", anchor="mm")
    for _ in range(26):
        gx = rng.randint(x0 + 40, x1 - 40)
        gy = rng.randint(1060, 1140)
        r = rng.randint(7, 11)
        d.ellipse([gx - r, gy - r, gx + r, gy + r],
                  fill="#D9A400", outline="#8A6D00", width=2)
    d.text((cx, 1095), lab["gold"], font=f_small,
           fill="#6B5300", anchor="mm")

    # Seta do fluxo (líquido subindo)
    f_flow = _font(30)
    for y in (980, 830, 680):
        d.polygon([(cx - 22, y + 34), (cx + 22, y + 34), (cx, y)],
                  fill="#2E86DE")
        d.rectangle([cx - 7, y + 34, cx + 7, y + 96], fill="#2E86DE")
    d.text((x1 + 130, 830), lab["flow"], font=f_flow,
           fill="#2E86DE", anchor="mm")

    # Linhas T (teste) e C (controle)
    f_line = _font(30)
    for y, tag, color in ((560, "T", "#D63031"), (380, "C", "#D63031")):
        d.rectangle([x0 + 24, y - 13, x1 - 24, y + 13], fill=color)
        d.ellipse([x0 - 44, y - 30, x0 + 8, y + 30], fill=color)
        d.text((x0 - 18, y), tag, font=_font(34), fill="white", anchor="mm")
    d.text((cx, 605), lab["test"], font=f_line, fill="#7A1F1F", anchor="mm")
    d.text((cx, 425), lab["control"], font=f_line, fill="#7A1F1F", anchor="mm")

    # Legenda (leitura do resultado)
    f_leg = _font(31)
    d.rounded_rectangle([90, 1380, STRIP_W - 90, 1530], radius=20,
                        fill="#1F3A5F")
    d.text((STRIP_W // 2, 1425), lab["legend_pos"], font=f_leg,
           fill="#FF6B6B", anchor="mm")
    d.text((STRIP_W // 2, 1485), lab["legend_neg"], font=f_leg,
           fill="white", anchor="mm")

    img.save(out_path, "PNG")
    return _asset(out_path, terms, language)


def _asset(out_path: str, terms: str, language: str):
    from ..media.providers import MediaAsset

    title = f"Test strip diagram — {terms}".strip()
    return MediaAsset(
        provider="synth",
        asset_id=f"synth-{_key(terms or 'test strip', language)}",
        title=title[:200],
        author="",
        license="Original (gerado por código)",
        license_url="",
        source_url="",
        download_url="",
        width=STRIP_W,
        height=STRIP_H,
        size_bytes=os.path.getsize(out_path),
        kind="image",
        local_path=out_path,
    )
