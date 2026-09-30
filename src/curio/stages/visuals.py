"""Estratégia visual por cena: a cena NUNCA fica sem visual.

O princípio que este módulo implementa: o requisito não é que a cena tenha
uma fotografia, é que ela tenha **um visual final**. Quando a fotografia
não é adequada ao conteúdo, trocar de medium é a resposta certa — não é
falha, e não é motivo para nenhuma imagem genérica entrar.

    literal         → foto relevante
    historical_art  → arte de domínio público → diagrama → cartão
    mechanism       → diagrama → cartão
    typographic     → cartão (a ideia É uma palavra)
    conceptual      → cartão conceitual → diagrama

Tudo aqui é gerado por código com Pillow, que o projeto já usa: sem rede,
sem licença de terceiros, sem dependência nova, e o PNG sai com o mesmo
formato de `MediaAsset` que o renderizador já consome. É por isso que o
renderizador não precisou ser tocado.
"""

from __future__ import annotations

import hashlib
import os

W, H = 1200, 1600

# A escada por tipo. A ordem importa e muda com o tipo: para uma cena de
# mecanismo, um diagrama vem ANTES de qualquer foto, porque foto de
# laboratório não mostra o processo.
LADDERS = {
    "literal": ("image", "art", "card"),
    # A spec não pede diagrama para histórico: sem arte de domínio público
    # achada, o certo é uma composição/cartão coerente. Um diagrama de
    # "fresco → monge → bird" não explica nada sobre São Francisco.
    "historical_art": ("art", "image", "card", "diagram"),
    "mechanism": ("diagram", "card"),
    "typographic": ("card",),
    "conceptual": ("card", "diagram"),
}

# Paleta: mesma identidade do resto do vídeo (fundo escuro do render) para
# o cartão não parecer um slide colado no meio do vídeo.
BG_TOP, BG_BOTTOM = (20, 24, 44), (34, 20, 62)
INK, INK_SOFT, ACCENT, ACCENT_2 = (245, 246, 250), (168, 176, 198), (86, 182, 255), (255, 190, 92)


def _key(*parts) -> str:
    return hashlib.sha256("|".join(str(p or "") for p in parts).lower().encode()).hexdigest()[:12]


def _font(size: int):
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


def _canvas():
    """Fundo vertical (o mesmo gradiente do fallback de render)."""
    from PIL import Image
    img = Image.new("RGB", (W, H), BG_TOP)
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)],
               fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t)
                          for i in range(3)))
    return img


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    """Quebra em linhas que cabem. Sem isso, um termo longo vira um traço
    ilegível atravessando o cartão."""
    words, lines, cur = str(text or "").split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) > max_w and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _asset(out_path: str, title: str, strategy: str, scene_id: int):
    """MediaAsset de material gerado — entra no vídeo como imagem normal.

    `provider="synth"` faz `classify_rights` marcar como `clear`: a obra é
    nossa, gerada por código, sem terceiro envolvido.
    """
    from ..media.providers import MediaAsset
    return MediaAsset(
        provider="synth",
        asset_id=f"synth-{_key(out_path)}",
        title=title[:200],
        author="",
        license="Original (gerado por código)",
        license_url="",
        source_url="",
        download_url="",
        width=W, height=H,
        size_bytes=os.path.getsize(out_path),
        kind="image",
        local_path=out_path,
        used_in=f"cena {scene_id}",
    )


def _out(cache_dir: str, kind: str, key: str) -> str:
    d = os.path.join(cache_dir, "synth")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{kind}_{key}.png")


# --- cartão tipográfico ------------------------------------------------

def render_card(subject: str, terms: list[str], narration: str,
                cache_dir: str, language: str = "pt-BR",
                scene_id: int = 0) -> object:
    """Cartão tipográfico: a ideia é uma palavra, então mostra-se a palavra.

    Ex.: "A palavra salário vem do latim salarium" → SALARIUM / SAL /
    SALÁRIO, em vez de uma foto de banco de moedas que não explica nada.
    O texto do cartão sai do que a cena JÁ declarou (subject, entities) —
    nunca é inventado aqui.
    """
    key = _key(subject, terms, language)
    out = _out(cache_dir, "card", key)
    if os.path.isfile(out) and os.path.getsize(out) > 10000:
        return _asset(out, f"Card — {subject or 'cena'}", "card", scene_id)

    from PIL import ImageDraw
    img = _canvas()
    d = ImageDraw.Draw(img)
    english = str(language or "").lower().startswith("en")

    f_kicker = _font(30)
    d.text((W // 2, 250), "ORIGEM" if english else "A PALAVRA VEM DE",
           font=f_kicker, fill=ACCENT_2, anchor="mm")

    # A palavra principal, grande, quebrada se preciso
    f_main = _font(96)
    principal = str(subject or "").strip() or "—"
    lines = _wrap(d, principal.upper(), f_main, W - 180)[:4]
    y = 420
    for line in lines:
        d.text((W // 2, y), line, font=f_main, fill=INK, anchor="mm")
        y += 118

    # Corrente de termos: subject → entities, que é a decomposição do tema
    chain = [str(t).strip() for t in (terms or []) if str(t).strip()][:4]
    if chain:
        f_chain = _font(46)
        y = max(y + 60, 720)
        d.line([(W // 2, y - 46), (W // 2, y - 18)], fill=ACCENT, width=5)
        d.polygon([(W // 2 - 20, y - 20), (W // 2 + 20, y - 20), (W // 2, y + 14)],
                  fill=ACCENT)
        for term in chain:
            d.text((W // 2, y + 62), term, font=f_chain, fill=INK_SOFT, anchor="mm")
            y += 96

    # Rodapé: a frase da cena, truncada. Dá contexto sem virar legenda
    # (a legenda queimada continua sendo a do TTS, intocada).
    f_foot = _font(30)
    frase = " ".join(str(narration or "").split())
    for i, line in enumerate(_wrap(d, frase, f_foot, W - 160)[:3]):
        d.text((W // 2, H - 210 + i * 42), line, font=f_foot,
               fill=(120, 128, 150), anchor="mm")

    img.save(out, "PNG")
    return _asset(out, f"Card — {subject or 'cena'}", "card", scene_id)


# --- diagrama genérico -------------------------------------------------

def render_diagram(subject: str, steps: list[str], narration: str,
                   cache_dir: str, language: str = "pt-BR",
                   scene_id: int = 0) -> object:
    """Fluxo vertical: a transformação, passo a passo.

    Cobre "flow", "process", "cause→effect", "before→after" e "layers" com
    uma só forma: uma sequência de estados ligados por setas. A diferença
    entre esses tipos é o TEXTO dos passos, que vem da cena — não são
    cinco renderizadores para manter.
    """
    key = _key(subject, steps, language)
    out = _out(cache_dir, "diagram", key)
    if os.path.isfile(out) and os.path.getsize(out) > 10000:
        return _asset(out, f"Diagrama — {subject or 'cena'}", "diagram", scene_id)

    from PIL import ImageDraw
    img = _canvas()
    d = ImageDraw.Draw(img)
    english = str(language or "").lower().startswith("en")

    f_head = _font(34)
    d.text((W // 2, 170), "HOW IT HAPPENS" if english else "COMO ACONTECE",
           font=f_head, fill=ACCENT, anchor="mm")

    f_step = _font(42)
    passos = [str(s).strip() for s in (steps or []) if str(s).strip()][:4]
    if not passos:
        # Sem passos declarados, o diagrama mostra o assunto: ainda é um
        # visual coerente, e não um placeholder vazio.
        passos = [str(subject or "—").strip() or "—"]

    top, bottom = 300, H - 300
    gap = (bottom - top) // max(1, len(passos))
    box_h = min(150, gap - 90)
    centers = [top + i * gap + box_h // 2 for i in range(len(passos))]

    # Conectores ANTES das caixas: desenhados depois, a ponta da seta
    # ficava coberta pela caixa seguinte e o fluxo virava um fio sem
    # direção — que é o oposto de "de → para".
    for i in range(len(passos) - 1):
        y0 = centers[i] + box_h // 2
        y1 = centers[i + 1] - box_h // 2
        if y1 - y0 < 18:
            continue
        d.line([(W // 2, y0 + 6), (W // 2, y1 - 20)], fill=ACCENT, width=5)
        d.polygon([(W // 2 - 19, y1 - 22), (W // 2 + 19, y1 - 22),
                   (W // 2, y1 + 4)], fill=ACCENT)

    for i, passo in enumerate(passos):
        cy = centers[i]
        d.rounded_rectangle([150, cy - box_h // 2, W - 150,
                             cy + box_h // 2], radius=26,
                            fill=(30, 36, 64), outline=ACCENT, width=3)
        for j, line in enumerate(_wrap(d, passo, f_step, W - 380)[:2]):
            d.text((W // 2, cy - 18 + j * 52), line, font=f_step,
                   fill=INK, anchor="mm")

    f_foot = _font(30)
    frase = " ".join(str(narration or "").split())
    for i, line in enumerate(_wrap(d, frase, f_foot, W - 160)[:2]):
        d.text((W // 2, H - 150 + i * 42), line, font=f_foot,
               fill=(120, 128, 150), anchor="mm")

    img.save(out, "PNG")
    return _asset(out, f"Diagrama — {subject or 'cena'}", "diagram", scene_id)


# --- a escada ----------------------------------------------------------

def strategies_for(ch) -> list[str]:
    """Escada de estratégias para a cena, do mais adequado ao menos."""
    vtype = str(getattr(ch, "visual_type", "") or "literal")
    return list(LADDERS.get(vtype, LADDERS["literal"]))


def _diagram_steps(ch) -> list[str]:
    """Passos do diagrama, na ordem: entidades e contexto da cena.

    A cena já sabe o que aparece (`visual_entities`) e o que rodeia
    (`context`); a sequência deles é a transformação que a cena explica.
    """
    out = [str(t).strip() for t in (getattr(ch, "visual_entities", []) or [])
           if str(t).strip()]
    out += [str(t).strip() for t in (getattr(ch, "context", []) or [])
            if str(t).strip()]
    return out[:4]


def build_visual(ch, strategy: str, cache_dir: str, language: str = "pt-BR",
                 narration: str = "") -> object | None:
    """Produz o visual pedido. None se não souber fazer esse tipo."""
    subject = str(getattr(ch, "subject", "") or "")
    terms = list(getattr(ch, "visual_queries", []) or [])
    scene_id = int(getattr(ch, "id", 0) or 0)
    if strategy == "card":
        return render_card(subject, terms, narration or
                           str(getattr(ch, "narration", "") or ""),
                           cache_dir, language, scene_id)
    if strategy == "diagram":
        return render_diagram(subject, _diagram_steps(ch), narration or
                              str(getattr(ch, "narration", "") or ""),
                              cache_dir, language, scene_id)
    return None


def visual_for_scene(ch, cache_dir: str, language: str = "pt-BR") -> object | None:
    """Primeira estratégia que este módulo sabe produzir para a cena.

    Só as estratégias de código (cartão, diagrama). Arte de domínio
    público e fotografia são busca de outra etapa: esta devolve None para
    elas, e a cena sobe/desce na escada até alguém entregar um visual.
    """
    for strategy in strategies_for(ch):
        asset = build_visual(ch, strategy, cache_dir, language)
        if asset is not None:
            return asset
    return None
