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
TELE_MAX_WORDS = 6
TELE_MAX_CHARS = 40


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
    cues = build_teleprompter_cues(chapters)
    doc = subs_stage.cues_to_ass(
        cues, width, height, TELE_FONT_SIZE, margin_v=60,
        alignment=5, border_style=3, back_colour="&HAA000000")
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return len(cues)
