"""Garantia: nenhum marcador de lista numerada chega às legendas.

Cobre o helper compartilhado, o sanitize do roteiro LLM e os dois
caminhos de cues (proporcional e WordBoundary).
"""

import re

from curio.stages.subs import (
    build_cues,
    cues_from_words,
    cues_to_ass,
    cues_to_srt,
    strip_list_markers,
    _normalize_subtitle_text,
)
from curio.stages.nvidia import _sanitize


def _plain_srt(text):
    return cues_to_srt(build_cues(text, 30.0))


def test_markers_no_inicio():
    assert strip_list_markers("0) Foo bar.") == "Foo bar."
    assert strip_list_markers("0), Foo bar.") == "Foo bar."
    assert strip_list_markers("1. Foo bar.") == "Foo bar."
    assert strip_list_markers("(2) Foo bar.") == "Foo bar."
    assert strip_list_markers("3: Foo bar.") == "Foo bar."


def test_markers_apos_frase():
    assert strip_list_markers("Foo. 1) Bar.") == "Foo. Bar."
    assert strip_list_markers("Foo? 2. Bar!") == "Foo? Bar!"
    assert strip_list_markers("Foo… 3) Bar.") == "Foo… Bar."


def test_markers_em_cadeia_e_quebra_de_linha():
    assert strip_list_markers("0) 1) Foo.") == "Foo."
    # helper não colapsa espaços (chamadores fazem isso); só remove marcadores
    assert strip_list_markers("Intro\n1) Foo\n2) Bar.") == "Intro\nFoo\nBar."


def test_preserva_conteudo_legitimo():
    assert strip_list_markers("Em 1990 foi um ano quente.") == "Em 1990 foi um ano quente."
    assert strip_list_markers("Vitamina B12 é importante.") == "Vitamina B12 é importante."
    assert strip_list_markers("O artigo 12, de 1990, vale.") == "O artigo 12, de 1990, vale."


def test_sanitize_llm():
    out = _sanitize("0), Primeiro ponto. 1. Segundo ponto! (2) Terceiro?", 4000)
    assert not re.search(r"\d+[).]", out.split()[0])
    assert "0)" not in out and "1." not in out.split(". ")[1][:2]
    assert out.startswith("Primeiro ponto.")


def test_normalize_e_cues():
    text = "0), Primeiro ponto. 1. Segundo ponto! (2) Terceiro?"
    norm = _normalize_subtitle_text(text)
    assert "0)" not in norm and norm.startswith("PRIMEIRO PONTO.")
    srt = _plain_srt(text)
    assert "0)" not in srt and "1." not in srt.replace("-->", "")
    ass = cues_to_ass(build_cues(text, 30.0), 1080, 1920, 60, 180)
    for line in ass.splitlines():
        if line.startswith("Dialogue:"):
            # Texto = após a 9ª vírgula (parse estilo libass); o Effect
            # deve estar vazio (vírgula ali corrompe o parse — bug do "0),").
            body = line.split(",", 10)[-1]
            assert not re.search(r"(^|\s)\(?\d[).]", re.sub(r"\{[^}]*\}", "", body))


def _libass_text(line: str) -> tuple[str, str]:
    """Divide Dialogue como o libass: 9 primeiras vírgulas delimitam."""
    parts = line.split(",", 9)
    assert len(parts) == 10, f"Dialogue malformado: {line[:80]}"
    return parts[8], parts[9]


def test_ass_effect_sem_virgula_regressao_0_paren():
    """Regressão do bug '0),' queimado em TODAS as legendas.

    O campo Effect continha `\\fad(300,0)`; a vírgula deslocava o parse do
    libass e o Texto virava `0),LEGENDA`. Effect deve ser vazio.
    """
    text = "Primeiro ponto. Segundo ponto!"
    ass = cues_to_ass(build_cues(text, 30.0), 1080, 1920, 60, 180)
    dialogues = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
    assert dialogues
    for line in dialogues:
        effect, body = _libass_text(line)
        assert "," not in effect, f"vírgula no Effect: {effect!r}"
        plain = re.sub(r"\{[^}]*\}", "", body)
        assert not plain.startswith("0)"), plain
        assert "0)," not in plain


def test_ass_estilo_contorno_3d_sem_caixa():
    """BorderStyle 1 (contorno grosso + sombra), sem caixa preta."""
    ass = cues_to_ass(build_cues("Olá mundo.", 5.0), 1080, 1920, 60, 180)
    style = next(ln for ln in ass.splitlines() if ln.startswith("Style:"))
    fields = style.split(",", 1)[1].split(",")
    # ...Fontsize, Primary, Secondary, Outline, Back, Bold, Italic,
    # Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle,
    # Outline, Shadow, Alignment, ...
    assert fields[14] == "1", fields  # BorderStyle
    assert int(fields[15]) >= 6, fields  # Outline grosso
    assert int(fields[16]) >= 3, fields  # Shadow deslocada


def test_destaque_usa_contorno_magenta():
    """Palavra de impacto: ciano com contorno magenta (sem vírgulas)."""
    ass = cues_to_ass(build_cues("Palavra impacto aqui.", 5.0),
                      1080, 1920, 60, 180)
    assert r"{\c&HFEF200&\3c&H5500FF&}" in ass
    assert r"\shad3\4c" not in ass


def test_cues_from_words_descarta_tokens():
    words = [
        {"text": "0)", "start": 0.0, "end": 0.2},
        {"text": "Olhe", "start": 0.2, "end": 0.5},
        {"text": "isto.", "start": 0.5, "end": 0.9},
        {"text": "1.", "start": 1.0, "end": 1.2},
        {"text": "Veja", "start": 1.2, "end": 1.5},
        {"text": "bem.", "start": 1.5, "end": 1.9},
    ]
    srt = cues_to_srt(cues_from_words(words))
    assert "0)" not in srt and "1." not in srt.replace("-->", "")
    assert "OLHE" in srt and "VEJA" in srt
