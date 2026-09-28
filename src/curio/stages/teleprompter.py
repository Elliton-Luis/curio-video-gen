"""Teleprompter humano (§17–20).

Gera um .ass com o texto da narração em fonte grande, centralizado, com caixa
semi-transparente — queimado sobre cópia do vídeo silencioso. Os tempos vêm
da estimativa por WPM (ajustável); servem só para leitura, NUNCA como
sincronia final (o áudio humano + Whisper é a fonte da verdade).
"""

from __future__ import annotations

from . import subs as subs_stage
from .scenes import Chapter

TELE_FONT_SIZE = 84
TELE_NEXT_FONT_SIZE = 56
TELE_MAX_WORDS = 6
TELE_MAX_CHARS = 40
# Últimos X segundos de cada bloco: texto atual fica amarelo (aviso de virada).
TELE_WARN_SECONDS = 0.7

WHITE = r"\c&H00FFFFFF&"
YELLOW = r"\c&H0000FFFF&"
DIM = r"\c&H00A0A0A0&"


def _safe(text: str) -> str:
    return text.replace("{", "").replace("}", "").replace("\\", "")


def _event_text(current: str, nxt: str, color: str) -> str:
    cur = f"{{\\fs{TELE_FONT_SIZE}{color}}}{_safe(current)}"
    if not nxt:
        return cur
    # DIM em bloco próprio: tag solta fora de {} vaza como texto na tela.
    return f"{cur}{{{DIM}}}\\N{{\\fs{TELE_NEXT_FONT_SIZE}}}{_safe(nxt)}"


def _tele_ass_doc(events: list[tuple[float, float, str]],
                  width: int, height: int) -> str:
    head = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Teleprompter,DejaVu Sans,{TELE_FONT_SIZE},&H00FFFFFF,&H000019FF,"
        f"&H80000000,&HAA000000,0,0,0,0,100,100,0,0,3,2,0,5,60,60,60,1\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    body = [f"Dialogue: 0,{subs_stage._fmt_ass_ts(s)},{subs_stage._fmt_ass_ts(e)},"
            f"Teleprompter,,0,0,0,,{text}" for s, e, text in events]
    return head + "\n".join(body) + "\n"


def build_teleprompter_cues(chapters: list[Chapter]) -> list[tuple[float, float, str]]:
    """Espalha blocos de cada capítulo pela sua duração estimada."""
    cues = []
    for ch in chapters:
        chunks = subs_stage.chunk_words(ch.narration.split(),
                                        TELE_MAX_WORDS, TELE_MAX_CHARS)
        if not chunks:
            continue
        weights = [len(c) + 1 for c in chunks]
        total = sum(weights)
        dur = max(ch.end - ch.start, ch.duration_estimate, 1.0)
        cursor = ch.start
        for i, (chunk, w) in enumerate(zip(chunks, weights)):
            share = dur * w / total
            end = ch.start + dur if i == len(chunks) - 1 else cursor + share
            cues.append((cursor, end, chunk))
            cursor = end
    return cues


def write_teleprompter_ass(chapters: list[Chapter], ass_path: str,
                           width: int, height: int) -> int:
    """Teleprompter de verdade: atual em destaque + próximo embaixo + virada.

    Cada evento mostra o bloco atual (grande, branco) e o seguinte (menor,
    cinza). Nos últimos TELE_WARN_SECONDS o atual fica amarelo — o leitor vê
    a mudança chegando. Blocos curtos demais mostram fase única.
    """
    cues = build_teleprompter_cues(chapters)
    texts = [t for _, _, t in cues]
    events = []
    for i, (start, end, text) in enumerate(cues):
        nxt = texts[i + 1] if i + 1 < len(texts) else ""
        if end - start > TELE_WARN_SECONDS + 0.5:
            mid = end - TELE_WARN_SECONDS
            events.append((start, mid, _event_text(text, nxt, WHITE)))
            events.append((mid, end, _event_text(text, nxt, YELLOW)))
        else:
            events.append((start, end, _event_text(text, nxt, WHITE)))
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(_tele_ass_doc(events, width, height))
    return len(cues)
