"""Low-level Pillow renderers for explicit local visual fallback plans."""

from __future__ import annotations

import hashlib
import os

from .visual_contracts import VisualFallbackPlan

W, H = 1200, 1600

# Piso de tamanho para considerar um PNG "pronto". Não é 10 KB: um
# gradiente escuro com uma palavra só (spotlight, cena sem entidades)
# comprime para pouco menos disso e é uma imagem válida — com o piso
# alto, essas cenas eram redesenhadas a cada execução, sem necessidade.
# 4 KB ainda rejeita arquivo truncado ou escrita pela metade.
MIN_PNG_BYTES = 4000

# Paleta: mesma identidade do resto do vídeo (fundo escuro do render) para
# o cartão não parecer um slide colado no meio do vídeo.
BG_TOP, BG_BOTTOM = (20, 24, 44), (34, 20, 62)
INK, INK_SOFT, ACCENT, ACCENT_2 = (245, 246, 250), (168, 176, 198), (86, 182, 255), (255, 190, 92)


def _key(*parts) -> str:
    return hashlib.sha256("|".join(str(p or "") for p in parts).lower().encode()).hexdigest()[:12]


def _font(size: int, typo=None, role: str = ""):
    """A fonte deste PAPEL, na fonte da voz principal quando não há papel.

    `typo` é o handle de `stages/typography.py` e chega pelo gênero; sem
    ele, o renderer usa uma sans pesada.

    O corpo é escalado pelo perfil, porque a mesma frase em itálico
    serifado ocupa menos linha do que em sans pesada, e um cartão de
    citação com o corpo do título estoura o quadro.
    """
    from PIL import ImageFont
    if typo is None or not role:
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
    return typo.pil(role, size)


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


# --- formas de visual --------------------------------------------------
# Um template só para tudo produz um vídeo em que seis cenas conceituais
# são a mesma tela com palavras diferentes — foi o que aconteceu com o
# vídeo de São Bento, em que 9 de 12 cenas viraram card e várias eram
# "São Bento name origin question" / "mystery" / "speculation": mesma
# forma, mesmo texto quase igual, nada a ver.
#
# A forma é escolhida pelo que a cena precisa COMUNICAR, não pelo seu
# tipo. Duas cenas do mesmo tipo podem (e devem) sair diferentes.

FORM_SPOTLIGHT = "spotlight"   # um termo, nada mais
FORM_DEFINITION = "definition"  # assunto + o que se decompõe
FORM_ENUM = "enumeration"       # assunto + lista de itens
FORM_CONTRAST = "contrast"     # X e Y lado a lado
FORM_QUOTE = "quote"           # a frase da cena, em destaque
FORM_DATED = "dated"           # nome + datas, para biografia de pessoa

FORMS = (FORM_SPOTLIGHT, FORM_DEFINITION, FORM_ENUM, FORM_CONTRAST,
         FORM_QUOTE, FORM_DATED)

def render_form(ch: VisualFallbackPlan, cache_dir: str,
                language: str = "pt-BR", typo=None) -> object:
    """Render a selected form from its validated fallback plan."""
    if not isinstance(ch, VisualFallbackPlan):
        raise TypeError("render_form requires a VisualFallbackPlan")
    if ch.strategy != "form":
        raise ValueError("render_form requires a form strategy")
    form = ch.form
    sujeito = str(getattr(ch, "subject", "") or "")
    narration = str(getattr(ch, "narration", "") or "")
    entities = [str(e).strip() for e in (getattr(ch, "visual_entities", []) or [])
                if str(e).strip()]
    context = [str(e).strip() for e in (getattr(ch, "context", []) or [])
               if str(e).strip()]
    scene_id = int(getattr(ch, "id", 0) or 0)
    # O gênero entra na chave do cache: o MESMO assunto desenhado em
    # `people` e em `science` têm aparência diferente, e devolver o PNG
    # cacheado do outro gênero mostraria a fonte errada sem erro nenhum.
    estilo = ""
    if typo is not None:
        estilo = str(getattr(typo.profile, "key", "") or "")
    key = _key(form, sujeito, entities, context, narration, language, estilo)
    out = _out(cache_dir, form, key)
    if os.path.isfile(out) and os.path.getsize(out) > MIN_PNG_BYTES:
        return _asset(out, f"{form} — {sujeito or 'cena'}", form, scene_id)

    from PIL import ImageDraw
    img = _canvas()
    d = ImageDraw.Draw(img)
    english = str(language or "").lower().startswith("en")

    # O papel que o assunto desta tela exerce. Um `spotlight` cujo
    # sujeito é o nome da pessoa usa `person`; um cujo sujeito é a palavra
    # em foco usa `term`. Sem isto o papel declarado pela cena só
    # chegava à forma de citação, e `mythology` — que põe o nome do mito
    # em itálico e o termo reto — desenhava os dois iguais.
    papel_assunto = ch.text_role
    if form == FORM_SPOTLIGHT:
        _draw_spotlight(d, sujeito, narration, english, typo, papel_assunto)
    elif form == FORM_ENUM:
        _draw_enum(d, sujeito, entities, narration, english, typo,
                   papel_assunto)
    elif form == FORM_CONTRAST:
        _draw_contrast(d, ch.contrast_sides[0], ch.contrast_sides[1],
                       narration, english, typo, papel_assunto)
    elif form == FORM_QUOTE:
        _draw_quote(d, ch.quote_text, english, typo, ch.text_role)
    elif form == FORM_DATED:
        _draw_dated(d, sujeito, ch.period, english, typo)
    else:
        return render_card(sujeito, list(ch.card_terms), narration, cache_dir,
                           language, scene_id, typo=typo,
                           word_card=ch.visual_type == "typographic")
    img.save(out, "PNG")
    return _asset(out, f"{form} — {sujeito or 'cena'}", form, scene_id)


def _footer(d, narration: str, linhas: int = 2, typo=None) -> None:
    """A frase da cena, discreta, sem virar legenda (a do TTS fica intacta).

    Papel `date`/`location` por herança: é texto de apoio, não narração,
    e é onde a direção de arte pede "metadado em variação discreta".
    """
    f = _font(30, typo, "location")
    frase = " ".join(str(narration or "").split())
    for i, line in enumerate(_wrap(d, frase, f, W - 160)[:linhas]):
        d.text((W // 2, H - 620 + i * 42), line, font=f,
               fill=(120, 128, 150), anchor="mm")


def _draw_spotlight(d, sujeito: str, narration: str, english: bool,
                    typo=None, papel: str = "") -> None:
    """Um termo, enorme, e quase nada mais. A forma mais silenciosa.

    Existe para as cenas cujo assunto já apareceu: repetir o layout
    completo duas vezes seguidas lê como erro de render, enquanto uma
    tela de uma palavra lê como decisão editorial.
    """
    f_kick = _font(30, typo, "kicker")
    d.text((W // 2, 360), "THE SUBJECT" if english else "O ASSUNTO",
           font=f_kick, fill=ACCENT_2, anchor="mm")
    # O sujeito da cena decide o papel. Em `mythology` o NOME do mito é
    # itálico e o termo não; com o papel fixo em "term" os dois saíam
    # iguais e a distinção que o perfil declara não chegava à tela.
    f_main = _font(112, typo, papel or "term")
    texto = (str(sujeito or "").strip()
             or " ".join(str(narration or "").split()[:8]).strip()
             or "—")
    linhas = _wrap(d, texto.upper(), f_main, W - 160)[:4]
    y = 590 - (len(linhas) - 1) * 68
    for line in linhas:
        d.text((W // 2, y), line, font=f_main, fill=INK, anchor="mm")
        y += 136
    d.line([(W // 2 - 90, y - 40), (W // 2 + 90, y - 40)], fill=ACCENT, width=5)
    _footer(d, narration, 2, typo)


def _draw_enum(d, sujeito: str, entities: list[str], narration: str,
               english: bool, typo=None, papel: str = "") -> None:
    """Assunto + lista numerada. Para cenas que enumeram qualidades ou itens."""
    f_head = _font(38, typo, papel or "term")
    d.text((W // 2, 210), str(sujeito or "").upper()[:34], font=f_head,
           fill=INK, anchor="mm")
    itens = entities or []
    if not itens:
        itens = [str(narration or "—").strip()[:40]]
    f_item = _font(46, typo, papel or "term")
    top, gap = 380, 190
    for i, item in enumerate(itens[:4]):
        y = top + i * gap
        d.ellipse([150, y - 34, 218, y + 34], fill=ACCENT)
        d.text((184, y), str(i + 1), font=_font(36, typo, papel or "term"),
               fill="#0f1117", anchor="mm")
        for j, line in enumerate(_wrap(d, item, f_item, W - 340)[:2]):
            d.text((250, y - 18 + j * 56), line, font=f_item, fill=INK_SOFT,
                   anchor="lm")
    _footer(d, narration, 2, typo)


def _draw_contrast(d, left: str, right: str, narration: str,
                   english: bool, typo=None, papel: str = "") -> None:
    """Duas colunas e uma divisória: isto NÃO é aquilo.

    Cenas negativas ("não tem relação com") precisam de um layout que
    não as apresente como equivalentes: um cartão de definição diria o
    contrário do que a cena afirma.
    """
    f_kick = _font(30, typo, "kicker")
    d.text((W // 2, 230), "THIS IS NOT" if english else "ISTO NÃO É",
           font=f_kick, fill=ACCENT_2, anchor="mm")
    f_side = _font(52, typo, papel or "term")
    meio = W // 2
    d.line([(meio, 460), (meio, 1280)], fill=(70, 78, 102), width=4)
    for x0, x1, texto, cor, marca in (
            (110, meio - 40, left, INK, "✕"),
            (meio + 40, W - 110, right, INK_SOFT, "≠")):
        d.text(((x0 + x1) // 2, 540), marca, font=_font(44, typo,
                                                        papel or "term"),
               fill=ACCENT, anchor="mm")
        y = 660
        for line in _wrap(d, str(texto or "—"), f_side, x1 - x0)[:4]:
            d.text(((x0 + x1) // 2, y), line, font=f_side, fill=cor, anchor="mm")
            y += 70
    _footer(d, narration, 2, typo)


def _draw_quote(d, frase: str, english: bool, typo=None, papel: str = "") -> None:
    """A frase da cena em destaque, entre aspas. Para a fala que importa.

    `papel` é o papel tipográfico do texto entre aspas. Quem chama passa
    o da cena quando ela declarou um, e `quote` quando não declarou: a
    forma DE CITAÇÃO já é a declaração de que aquele texto é voz de
    terceiro, e é isso que a coloca em itálico serifado num vídeo de
    História de Pessoas. Sem este caminho, o projeto antigo — cujas cenas
    não têm `text_role` — perderia justamente o itálico que torna a
    citação legível como citação.
    """
    papel = papel or "quote"
    f_mark = _font(150, typo, papel)
    d.text((W // 2, 430), "“", font=f_mark, fill=ACCENT, anchor="mm")
    f_quote = _font(50, typo, papel)
    linhas = _wrap(d, frase, f_quote, W - 260)[:6]
    y = 640 - (len(linhas) - 1) * 34
    for line in linhas:
        d.text((W // 2, y), line, font=f_quote, fill=INK, anchor="mm")
        y += 68
    d.text((W // 2, min(y + 30, H - 420)), "”", font=f_mark, fill=ACCENT,
           anchor="mm")


def _draw_dated(d, nome: str, datas: str, english: bool, typo=None) -> None:
    """O nome na serifada principal e a data embaixo, discreta.

    É a forma que a direção de arte pede para biografia:

        SÃO BENTO DE NÚRSIA
        c. 480 — 547

    Os dois textos são da MESMA família, e é a hierarquia que separa, não
    a fonte: o nome no papel `person` e a data no papel `date`, que nos
    gêneros editoriais é uma sans menor. Trocar a família entre os dois
    produziria um nome em serifa e uma data em itálico, e a data pararia
    de parecer metadado para parecer outra citação.
    """
    f_nome = _font(96, typo, "person")
    nome_txt = str(nome or "—").upper()
    linhas = _wrap(d, nome_txt, f_nome, W - 180)[:3]
    y = 600 - (len(linhas) - 1) * 62
    for line in linhas:
        d.text((W // 2, y), line, font=f_nome, fill=INK, anchor="mm")
        y += 124
    d.line([(W // 2 - 110, y - 30), (W // 2 + 110, y - 30)], fill=ACCENT,
           width=5)
    if datas:
        f_data = _font(46, typo, "date")
        d.text((W // 2, y + 74), str(datas), font=f_data, fill=ACCENT_2,
               anchor="mm")


def render_card(subject: str, terms: list[str], narration: str,
                cache_dir: str, language: str = "pt-BR",
                scene_id: int = 0, typo=None,
                word_card: bool = False) -> object:
    """Cartão tipográfico: a ideia é uma palavra, então mostra-se a palavra.

    Ex.: "A palavra salário vem do latim salarium" → SALARIUM / sal /
    salário, em vez de uma foto de banco de moedas que não explica nada.
    Assunto, termos e papel de cartão chegam resolvidos pela política de
    fallback; este módulo só os desenha.

    A cadeia é o lugar onde a tipografia vira explicação, e não enfeite:
    as formas históricas recebem o tratamento documental (itálico nos
    gêneros editoriais) e a forma atual fica no corpo de destaque. É a
    transformação da palavra mostrada com o desenho mudando, que é o que
    a direção de arte pede para Etimologia — e não a mesma fonte repetida
    em corpo menor, que é o que cartão sempre fez.
    """
    estilo = ""
    if typo is not None:
        estilo = str(getattr(typo.profile, "key", "") or "")
    key = _key("card-layout-v2", subject, terms, language, estilo)
    out = _out(cache_dir, "card", key)
    if os.path.isfile(out) and os.path.getsize(out) > MIN_PNG_BYTES:
        return _asset(out, f"Card — {subject or 'cena'}", "card", scene_id)

    from PIL import ImageDraw
    img = _canvas()
    d = ImageDraw.Draw(img)
    english = str(language or "").lower().startswith("en")

    f_kicker = _font(30, typo, "kicker")
    d.text((W // 2, 360),
           ("ORIGEM" if english else "A PALAVRA VEM DE") if word_card
           else ("KEY IDEA" if english else "IDEIA-CHAVE"),
           font=f_kicker, fill=ACCENT_2, anchor="mm")

    # A palavra principal vem pronta da política. Texto narrado não vira
    # assunto visual por inferência no renderer.
    f_main = _font(96, typo, "term")
    principal = str(subject or "").strip() or "—"
    lines = _wrap(d, principal.upper(), f_main, W - 180)[:4]
    y = 520
    for line in lines:
        d.text((W // 2, y), line, font=f_main, fill=INK, anchor="mm")
        y += 118

    # Corrente: a decomposição do assunto que a cena declarou.
    # Search representations are not an explanatory chain. Only typographic
    # scenes have declared word morphology/entities suitable for this layout.
    chain = [str(term).strip() for term in (terms or [])
             if str(term).strip()][:4]
    if chain:
        # A forma que a cadeia desemboca é o elemento em DESTAQUE da
        # tela, e é o papel `emphasis` que existe para isso. O termo
        # (`term`) é o assunto da cena; o destaque é a palavra em que a
        # transformação chega.
        f_chain = _font(46, typo, "document")
        f_atual = _font(46, typo, "emphasis")
        y = max(y + 60, 810)
        d.line([(W // 2, y - 46), (W // 2, y - 18)], fill=ACCENT, width=5)
        d.polygon([(W // 2 - 20, y - 20), (W // 2 + 20, y - 20), (W // 2, y + 14)],
                  fill=ACCENT)
        ultimo = len(chain) - 1
        for i, term in enumerate(chain):
            # A última é a forma que a cadeia desemboca — a palavra de
            # hoje, ligada à grande de cima. As anteriores são o caminho
            # histórico, e é nele que o itálico editorial entra.
            d.text((W // 2, y + 62), term,
                   font=f_atual if i == ultimo else f_chain,
                   fill=INK if i == ultimo else INK_SOFT, anchor="mm")
            y += 96

    # Rodapé: a frase da cena, truncada. Dá contexto sem virar legenda
    # (a legenda queimada continua sendo a do TTS, intocada).
    f_foot = _font(30, typo, "location")
    frase = " ".join(str(narration or "").split())
    footer_lines = _wrap(d, frase, f_foot, W - 160)
    if len(footer_lines) > 2:
        excerpt = footer_lines[1].rstrip()
        while excerpt and d.textbbox((0, 0), excerpt + "…", font=f_foot)[2] > W - 160:
            excerpt = excerpt[:-1].rstrip()
        footer_lines[1] = excerpt + "…"
    footer_top = H - 260 if chain else max(y + 180, int(H * 0.53))
    for i, line in enumerate(footer_lines[:2]):
        d.text((W // 2, footer_top + i * 42), line, font=f_foot,
               fill=(120, 128, 150), anchor="mm")

    img.save(out, "PNG")
    return _asset(out, f"Card — {subject or 'cena'}", "card", scene_id)


# --- diagrama genérico -------------------------------------------------

def render_diagram(subject: str, steps: list[str], narration: str,
                   cache_dir: str, language: str = "pt-BR",
                   scene_id: int = 0, typo=None) -> object:
    """Fluxo vertical: a transformação, passo a passo.

    Cobre "flow", "process", "cause→effect", "before→after" e "layers" com
    uma só forma: uma sequência de estados ligados por setas. A diferença
    entre esses tipos é o TEXTO dos passos, que vem da cena — não são
    cinco renderizadores para manter.
    """
    estilo = ""
    if typo is not None:
        estilo = str(getattr(typo.profile, "key", "") or "")
    # Narration is rendered in the footer, so it is part of the visual bytes
    # and must participate in the cache identity. Omitting it reused the first
    # scene's caption for later scenes with the same topic and empty steps.
    key = _key(subject, steps, narration, language, estilo)
    out = _out(cache_dir, "diagram", key)
    if os.path.isfile(out) and os.path.getsize(out) > MIN_PNG_BYTES:
        return _asset(out, f"Diagrama — {subject or 'cena'}", "diagram", scene_id)

    from PIL import ImageDraw
    img = _canvas()
    d = ImageDraw.Draw(img)
    english = str(language or "").lower().startswith("en")

    f_head = _font(34, typo, "kicker")
    d.text((W // 2, 360), "HOW IT HAPPENS" if english else "COMO ACONTECE",
           font=f_head, fill=ACCENT, anchor="mm")

    f_step = _font(42, typo, "term")
    passos = [str(s).strip() for s in (steps or []) if str(s).strip()][:4]
    if not passos:
        # Sem passos declarados, o diagrama mostra o assunto: ainda é um
        # visual coerente, e não um placeholder vazio.
        passos = [str(subject or "—").strip() or "—"]

    top, bottom = 480, H - 620
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

    f_foot = _font(30, typo, "location")
    frase = " ".join(str(narration or "").split())
    for i, line in enumerate(_wrap(d, frase, f_foot, W - 160)[:2]):
        d.text((W // 2, H - 620 + i * 42), line, font=f_foot,
               fill=(120, 128, 150), anchor="mm")

    img.save(out, "PNG")
    return _asset(out, f"Diagrama — {subject or 'cena'}", "diagram", scene_id)


def render_fallback_plan(plan: VisualFallbackPlan, cache_dir: str,
                         language: str = "pt-BR", genre: str = ""):
    """Render an already resolved fallback instruction without scene inference."""
    from . import typography as typo_stage
    typo = typo_stage.for_genre(genre)
    if plan.strategy == "diagram":
        return render_diagram(plan.subject, list(plan.steps), plan.narration,
                              cache_dir, language, plan.scene_id, typo)
    if plan.strategy == "form":
        return render_form(plan, cache_dir, language, typo)
    raise ValueError(f"unsupported fallback strategy: {plan.strategy}")
