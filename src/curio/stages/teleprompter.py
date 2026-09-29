"""Teleprompter humano (§17–20).

Gera um .ass com o texto da narração em fonte grande, centralizado, com caixa
semi-transparente — queimado sobre cópia do vídeo silencioso. Os tempos vêm
da estimativa por WPM (ajustável); servem só para leitura, NUNCA como
sincronia final (o áudio humano + Whisper é a fonte da verdade).
"""

from __future__ import annotations

from . import subs as subs_stage
from .scenes import Chapter

TELE_FONT_SIZE = 104
TELE_NEXT_FONT_SIZE = 64
TELE_MARK_FONT_SIZE = 48
TELE_MAX_WORDS = 5
TELE_MAX_CHARS = 34
# Últimos X segundos de cada bloco: texto atual fica amarelo (aviso de virada).
TELE_WARN_SECONDS = 0.7
# Última fala antes de trocar de cena: aviso mais longo (a virada importa).
TELE_SCENE_WARN_SECONDS = 1.4

WHITE = r"\c&H00FFFFFF&"
YELLOW = r"\c&H0000FFFF&"
DIM = r"\c&H00A0A0A0&"
# Próximo bloco quando abre cena nova: ciano claro (≠ cinza = continua).
NEXT_SCENE = r"\c&H00A0FFFF&"
MARK = r"\c&H00808080&"


def _safe(text: str) -> str:
    return text.replace("{", "").replace("}", "").replace("\\", "")


def _event_text(current: str, nxt: str, color: str,
                nxt_new_scene: bool = False) -> str:
    cur = f"{{\\fs{TELE_FONT_SIZE}{color}}}{_safe(current)}"
    if not nxt:
        return cur
    # DIM em bloco próprio: tag solta fora de {} vaza como texto na tela.
    if nxt_new_scene:
        # Cena nova chegando: separador + próximo em ciano (≠ cinza).
        mark = (f"{{\\fs{TELE_MARK_FONT_SIZE}{MARK}}}"
                "\\N··· próxima parte ···\\N")
        return (f"{cur}{mark}{{{NEXT_SCENE}}}"
                f"{{\\fs{TELE_NEXT_FONT_SIZE}}}{_safe(nxt)}")
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
        "Alignment, MarginL, MarginR, MarginV, Encoding, LineSpacing\n"
        f"Style: Teleprompter,DejaVu Sans,{TELE_FONT_SIZE},&H00FFFFFF,&H000019FF,"
        f"&H80000000,&HCC000000,1,0,0,0,100,100,0,0,3,2,0,5,120,120,60,1,12\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    body = [f"Dialogue: 0,{subs_stage._fmt_ass_ts(s)},{subs_stage._fmt_ass_ts(e)},"
            f"Teleprompter,,0,0,0,,{text}" for s, e, text in events]
    return head + "\n".join(body) + "\n"


def build_teleprompter_cues(chapters: list[Chapter]
                            ) -> list[tuple[float, float, str, int]]:
    """Espalha blocos de cada capítulo pela sua duração estimada.

    Retorna (início, fim, bloco, id_do_capítulo). Tempos idênticos a
    antes — só carrega o capítulo junto para marcar viradas de cena.
    """
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
            cues.append((cursor, end, chunk, ch.id))
            cursor = end
    return cues


def write_teleprompter_ass(chapters: list[Chapter], ass_path: str,
                           width: int, height: int) -> int:
    """Teleprompter de verdade: atual em destaque + próximo embaixo + virada.

    Cada evento mostra o bloco atual (grande, branco, negrito) e o seguinte
    (menor: cinza = continua; ciano + separador = cena nova chegando). Nos
    últimos instantes o atual fica amarelo — o leitor vê a mudança chegando,
    com aviso mais longo no fim de cada cena. Só decoração: texto e tempos
    da narração intactos.
    """
    cues = build_teleprompter_cues(chapters)
    events = []
    for i, (start, end, text, cid) in enumerate(cues):
        nxt = cues[i + 1][2] if i + 1 < len(cues) else ""
        nxt_new_scene = bool(nxt) and cues[i + 1][3] != cid
        warn = TELE_SCENE_WARN_SECONDS if nxt_new_scene else TELE_WARN_SECONDS
        if end - start > warn + 0.5:
            mid = end - warn
            events.append((start, mid,
                           _event_text(text, nxt, WHITE, nxt_new_scene)))
            events.append((mid, end,
                           _event_text(text, nxt, YELLOW, nxt_new_scene)))
        else:
            events.append((start, end,
                           _event_text(text, nxt, WHITE, nxt_new_scene)))
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(_tele_ass_doc(events, width, height))
    return len(cues)
