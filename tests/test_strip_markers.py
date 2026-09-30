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
            # NOTA: o campo Effect é sempre \fad(300,0) — contém vírgula,
            # então o texto é o que vem após a 10ª vírgula (não a 9ª).
            body = line.split(",", 10)[-1]
            assert not re.search(r"(^|\s)\(?\d[).]", re.sub(r"\{[^}]*\}", "", body))


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
