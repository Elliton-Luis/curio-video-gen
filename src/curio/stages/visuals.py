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
import re

W, H = 1200, 1600

# Piso de tamanho para considerar um PNG "pronto". Não é 10 KB: um
# gradiente escuro com uma palavra só (spotlight, cena sem entidades)
# comprime para pouco menos disso e é uma imagem válida — com o piso
# alto, essas cenas eram redesenhadas a cada execução, sem necessidade.
# 4 KB ainda rejeita arquivo truncado ou escrita pela metade.
MIN_PNG_BYTES = 4000

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


def _role(ch, padrao: str) -> str:
    """O papel tipográfico de um elemento desta cena.

    O papel DECLARADO pela cena vence o papel que a forma sugere. A forma
    de citação já sugere `quote`, então uma cena que declarou `latin`
    entra em itálico serifado como latim — que é o mesmo desenho, mas com
    o nome certo no metadata e no relatório. A forma só define o papel
    quando a cena não disse nada, e é por isso que uma cena de capítulos
    antigos (sem `text_role`) ainda sai em itálico.
    """
    try:
        from .scenes import text_role_for
        return text_role_for(ch) or padrao
    except Exception:  # noqa: BLE001 — papel nunca é fatal para o render
        return padrao


def _key(*parts) -> str:
    return hashlib.sha256("|".join(str(p or "") for p in parts).lower().encode()).hexdigest()[:12]


def _font(size: int, typo=None, role: str = ""):
    """A fonte deste PAPEL, na fonte da voz principal quando não há papel.

    `typo` é o handle de `stages/typography.py` e chega pelo gênero; sem
    ele, o comportamento é exatamente o de antes: uma sans pesada para
    tudo. É o que mantém `render_form(ch, form, cache_dir)` funcionando
    igual em quem não usa o recurso.

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


# --- cartão tipográfico ------------------------------------------------

def _card_chain(ch) -> list[str]:
    """A cadeia do cartão: o que a cena decompõe o assunto em.

    Vem das ENTIDADES da cena, não das consultas de busca. A diferença
    importa: para "A palavra salário vem do latim salarium", as entidades
    são `sal` e `romano` — a cadeia que o cartão deve mostrar — enquanto
    as consultas são `salarium, roman salt`, que é o que foi digitado no
    buscador e repetiria a palavra grande logo abaixo dela.

    Qualquer termo igual ao assunto sai da cadeia: repetir "SALARIUM" em
    corpo pequeno sob "SALARIUM" em corpo grande parece defeito, não
    etimologia.
    """
    out: list[str] = []
    visto = {str(getattr(ch, "subject", "") or "").strip().lower()}
    for termo in list(getattr(ch, "visual_entities", []) or []):
        s = str(termo).strip()
        if s and s.lower() not in visto:
            visto.add(s.lower())
            out.append(s)
    if not out:
        for termo in list(getattr(ch, "context", []) or []):
            s = str(termo).strip()
            if s and s.lower() not in visto:
                visto.add(s.lower())
                out.append(s)
    return out[:4]


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

FORMS = (FORM_SPOTLIGHT, FORM_DEFINITION, FORM_ENUM, FORM_CONTRAST,
         FORM_QUOTE)

_FORM_FOR_TYPE = {
    "typographic": FORM_DEFINITION,
    "mechanism": FORM_ENUM,
    "conceptual": FORM_DEFINITION,
    "historical_art": FORM_SPOTLIGHT,
    "literal": FORM_ENUM,
}


def _contrast_pair(ch) -> tuple[str, str] | None:
    """Detecta "X e não Y"/"X versus Y" na cena: vira um visual de contraste.

    Cenas como "Michel Temer não tem relação com São Bento" pedem
    explicitamente uma negativa, e um cartão de definição mente sobre
    elas: mostra as duas coisas como se fossem equivalentes.
    """
    subj = str(getattr(ch, "subject", "") or "")
    ents = [str(e).strip() for e in (getattr(ch, "visual_entities", []) or [])
            if str(e).strip()]
    if len(ents) >= 2 and re.search(
            r"\b(no|nao|não|not|without|versus|vs)\b",
            (subj + " " + " ".join(ents)).lower()):
        return ents[0], ents[1]
    return None


def _quote_line(narration: str) -> str:
    """A frase mais marcante da cena, para um visual de citação.

    Pega a primeira frase com tamanho de fala real e corta em um limite
    de palavra. Sem isso, a forma `quote` não teria o que mostrar.
    """
    for sent in re.split(r"(?<=[.!?…])\s+", (narration or "").strip()):
        sent = sent.strip()
        if len(sent.split()) >= 4:
            palavras = sent.split()
            return " ".join(palavras[:12]) + ("…" if len(palavras) > 12 else "")
    return ""


class VisualState:
    """O que o vídeo já usou, para a próxima cena não repetir.

    Duas peças: as FORMAS já exibidas e os ASSUNTOS já exibidos. Um
    assunto quase igual ao de uma cena anterior não pode receber a mesma
    forma — é aí que dois "name origin" viram duas telas com a mesma
    cara. Nestas, a forma vira `spotlight` de propósito: mínima, honesta
    e visualmente distinta.
    """

    # Um "não" no começo muda o sentido, não o assunto. "São Bento name
    # origin question" e "Lack of São Bento name origin information" são
    # o mesmo assunto visto de dois jeitos, e comparar os token inteiros
    # dá 0,5 de similaridade — logo abaixo do corte, e as duas cenas
    # saíam com o mesmo layout.
    _NEGACOES = {"lack", "falta", "missing", "absence", "no", "nao", "não",
                 "nothing", "nada", "sem"}

    def __init__(self) -> None:
        self.forms: list[str] = []
        self.subjects: list[str] = []

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

    @classmethod
    def _core(cls, s: str) -> set[str]:
        toks = [t for t in cls._norm(s).split() if t not in cls._NEGACOES]
        return set(toks)

    def subject_repeated(self, subject: str) -> bool:
        """O assunto desta cena já apareceu, palavra a palavra?"""
        novo = self._norm(subject)
        if not novo:
            return False
        for visto in self.subjects:
            if novo == visto:
                return True
            a, b = self._core(subject), set(visto.split())
            if a and b and len(a & b) / len(a | b) >= 0.5:
                return True
        return False

    def record(self, subject: str, form: str) -> None:
        if form and form not in self.forms:
            self.forms.append(form)
        s = self._norm(subject)
        if s and s not in self.subjects:
            self.subjects.append(s)

    def form_used(self, form: str) -> int:
        return self.forms.count(form) if self.forms.count(form) else 0


def choose_form(ch, state: "VisualState | None" = None,
                genre: str = "") -> str:
    """A forma que esta cena deve usar, dada o que o vídeo já mostrou."""
    from . import editorial
    perfil = editorial.get(genre)
    vtype = str(getattr(ch, "visual_type", "") or "literal")
    sujeito = str(getattr(ch, "subject", "") or "")
    narration = str(getattr(ch, "narration", "") or "")
    ents = [e for e in (getattr(ch, "visual_entities", []) or [])
            if str(e).strip()]

    # 1) a cena pede explicitamente uma negativa → contraste
    if _contrast_pair(ch) is not None:
        base = FORM_CONTRAST
    # 2) assunto repetido → spotlight, para não virar cópia da anterior
    elif state is not None and state.subject_repeated(sujeito):
        base = FORM_SPOTLIGHT
    # 3) o perfil do gênero tem forma preferida; senão, a do tipo
    elif perfil is not None and perfil.visual.preferred_forms:
        base = perfil.visual.preferred_forms[0]
    else:
        base = _FORM_FOR_TYPE.get(vtype, FORM_DEFINITION)

    # 4) subjectively poor and the type already saturated: try another form
    #    that is valid for this scene, preferring one not yet used.
    if state is not None and base != FORM_SPOTLIGHT:
        candidatos = [base]
        if not ents:
            candidatos.append(FORM_SPOTLIGHT)
        else:
            candidatos += [f for f in (FORM_ENUM, FORM_DEFINITION)
                           if f not in candidatos]
        if _quote_line(narration):
            candidatos.append(FORM_QUOTE)
        for cand in candidatos:
            if cand not in state.forms:
                return cand
    return base


def render_form(ch, form: str, cache_dir: str, language: str = "pt-BR",
                typo=None) -> object:
    """Desenha a forma pedida. Cacheado por (forma, assunto, conteúdo, fonte).

    `typo` é opcional e fica no fim da assinatura de propósito: quem já
    chamava `render_form(ch, form, cache_dir)` continua funcionando com a
    fonte de sempre, sem gênero.
    """
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
    papel_assunto = _role(ch, "term")
    if form == FORM_SPOTLIGHT:
        _draw_spotlight(d, sujeito, narration, english, typo, papel_assunto)
    elif form == FORM_ENUM:
        _draw_enum(d, sujeito, entities, narration, english, typo,
                   papel_assunto)
    elif form == FORM_CONTRAST:
        par = _contrast_pair(ch)
        _draw_contrast(d, par[0] if par else sujeito, par[1] if par else "",
                       narration, english, typo, papel_assunto)
    elif form == FORM_QUOTE:
        _draw_quote(d, _quote_line(narration) or sujeito, english, typo,
                    _role(ch, "quote"))
    else:
        return render_card(sujeito, entities + context, narration, cache_dir,
                           language, scene_id, ch=ch, typo=typo)
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
        d.text((W // 2, H - 150 + i * 42), line, font=f,
               fill=(120, 128, 150), anchor="mm")


def _draw_spotlight(d, sujeito: str, narration: str, english: bool,
                    typo=None, papel: str = "") -> None:
    """Um termo, enorme, e quase nada mais. A forma mais silenciosa.

    Existe para as cenas cujo assunto já apareceu: repetir o layout
    completo duas vezes seguidas lê como erro de render, enquanto uma
    tela de uma palavra lê como decisão editorial.
    """
    f_kick = _font(30, typo, "kicker")
    d.text((W // 2, 520), "THE SUBJECT" if english else "O ASSUNTO",
           font=f_kick, fill=ACCENT_2, anchor="mm")
    # O sujeito da cena decide o papel. Em `mythology` o NOME do mito é
    # itálico e o termo não; com o papel fixo em "term" os dois saíam
    # iguais e a distinção que o perfil declara não chegava à tela.
    f_main = _font(112, typo, papel or "term")
    linhas = _wrap(d, str(sujeito or "—").upper(), f_main, W - 160)[:4]
    y = 720 - (len(linhas) - 1) * 68
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
    d.line([(meio, 340), (meio, 1120)], fill=(70, 78, 102), width=4)
    for x0, x1, texto, cor, marca in (
            (110, meio - 40, left, INK, "✕"),
            (meio + 40, W - 110, right, INK_SOFT, "≠")):
        d.text(((x0 + x1) // 2, 430), marca, font=_font(44, typo,
                                                        papel or "term"),
               fill=ACCENT, anchor="mm")
        y = 540
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


def render_card(subject: str, terms: list[str], narration: str,
                cache_dir: str, language: str = "pt-BR",
                scene_id: int = 0, ch=None, typo=None) -> object:
    """Cartão tipográfico: a ideia é uma palavra, então mostra-se a palavra.

    Ex.: "A palavra salário vem do latim salarium" → SALARIUM / sal /
    salário, em vez de uma foto de banco de moedas que não explica nada.
    O texto do cartão sai do que a cena JÁ declarou (subject, entities) —
    nunca é inventado aqui.

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
    key = _key(subject, terms, language, estilo)
    out = _out(cache_dir, "card", key)
    if os.path.isfile(out) and os.path.getsize(out) > MIN_PNG_BYTES:
        return _asset(out, f"Card — {subject or 'cena'}", "card", scene_id)

    from PIL import ImageDraw
    img = _canvas()
    d = ImageDraw.Draw(img)
    english = str(language or "").lower().startswith("en")

    f_kicker = _font(30, typo, "kicker")
    d.text((W // 2, 250), "ORIGEM" if english else "A PALAVRA VEM DE",
           font=f_kicker, fill=ACCENT_2, anchor="mm")

    # A palavra principal, grande, quebrada se preciso
    f_main = _font(96, typo, "term")
    principal = str(subject or "").strip() or "—"
    lines = _wrap(d, principal.upper(), f_main, W - 180)[:4]
    y = 420
    for line in lines:
        d.text((W // 2, y), line, font=f_main, fill=INK, anchor="mm")
        y += 118

    # Corrente: a decomposição do assunto que a cena declarou.
    chain = _card_chain(ch) if ch is not None else [
        str(t).strip() for t in (terms or []) if str(t).strip()][:4]
    if chain:
        f_chain = _font(46, typo, "document")
        f_atual = _font(46, typo, "term")
        y = max(y + 60, 720)
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
    for i, line in enumerate(_wrap(d, frase, f_foot, W - 160)[:3]):
        d.text((W // 2, H - 210 + i * 42), line, font=f_foot,
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
    key = _key(subject, steps, language, estilo)
    out = _out(cache_dir, "diagram", key)
    if os.path.isfile(out) and os.path.getsize(out) > MIN_PNG_BYTES:
        return _asset(out, f"Diagrama — {subject or 'cena'}", "diagram", scene_id)

    from PIL import ImageDraw
    img = _canvas()
    d = ImageDraw.Draw(img)
    english = str(language or "").lower().startswith("en")

    f_head = _font(34, typo, "kicker")
    d.text((W // 2, 170), "HOW IT HAPPENS" if english else "COMO ACONTECE",
           font=f_head, fill=ACCENT, anchor="mm")

    f_step = _font(42, typo, "term")
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

    f_foot = _font(30, typo, "location")
    frase = " ".join(str(narration or "").split())
    for i, line in enumerate(_wrap(d, frase, f_foot, W - 160)[:2]):
        d.text((W // 2, H - 150 + i * 42), line, font=f_foot,
               fill=(120, 128, 150), anchor="mm")

    img.save(out, "PNG")
    return _asset(out, f"Diagrama — {subject or 'cena'}", "diagram", scene_id)


# --- a escada ----------------------------------------------------------

def strategies_for(ch, genre: str = "") -> list[str]:
    """Escada de estratégias para a cena, do mais adequado ao menos.

    O perfil editorial pode antecipar a escada: um gênero científico não deve
    receber foto decorativa de laboratório antes do diagrama, e um de
    etimologia não deve tentar fotografar uma palavra. A escada do perfil
    é declarada para CADA medium, e a do tipo visual só completa o que
    faltar.
    """
    from . import editorial
    perfil = editorial.get(genre)
    vtype = str(getattr(ch, "visual_type", "") or "literal")
    if perfil is not None and perfil.visual.ladder:
        base = list(perfil.visual.ladder)
    else:
        base = list(LADDERS.get(vtype, LADDERS["literal"]))
    for s in LADDERS.get(vtype, LADDERS["literal"]):
        if s not in base:
            base.append(s)
    return base


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
                 narration: str = "", typo=None) -> object | None:
    """Produz o visual pedido. None se não souber fazer esse tipo."""
    subject = str(getattr(ch, "subject", "") or "")
    terms = list(getattr(ch, "visual_queries", []) or [])
    scene_id = int(getattr(ch, "id", 0) or 0)
    if strategy == "card":
        return render_card(subject, terms, narration or
                           str(getattr(ch, "narration", "") or ""),
                           cache_dir, language, scene_id, ch=ch, typo=typo)
    if strategy == "diagram":
        return render_diagram(subject, _diagram_steps(ch), narration or
                              str(getattr(ch, "narration", "") or ""),
                              cache_dir, language, scene_id, typo=typo)
    return None


def visual_for_scene(ch, cache_dir: str, language: str = "pt-BR",
                     state: "VisualState | None" = None,
                     genre: str = "") -> object | None:
    """Primeira estratégia que este módulo sabe produzir para a cena.

    Só as estratégias de código (cartão, diagrama, e as formas visuais
   各种). Arte de domínio público e fotografia são busca de outra etapa:
    esta devolve None para elas, e a cena sobe/desce na escada até
    alguém entregar um visual.

    `state` carrega o que o vídeo já mostrou, para que a forma escolhida
    não repita a da cena anterior quando o assunto também repete.
    """
    # O gênero já chega neste ponto, então o handle de tipografia nasce
    # aqui e não precisa atravessar o pipeline. `genre=""` devolve um
    # handle sem perfil, que resolve para a fonte de sempre: um vídeo sem
    # gênero sai com a mesma cara de antes.
    from . import typography as _typo
    typo = _typo.for_genre(genre)

    for strategy in strategies_for(ch, genre):
        if strategy in FORMS:
            forma = choose_form(ch, state, genre)
            asset = render_form(ch, forma, cache_dir, language, typo)
            if asset is not None:
                if state is not None:
                    state.record(str(getattr(ch, "subject", "") or ""), forma)
                return asset
            continue
        asset = build_visual(ch, strategy, cache_dir, language, typo=typo)
        if asset is not None:
            if state is not None:
                state.record(str(getattr(ch, "subject", "") or ""), strategy)
            return asset
    return None
