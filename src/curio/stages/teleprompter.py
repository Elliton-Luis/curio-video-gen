"""Teleprompter humano (§17–20).

Gera um .ass com o texto da narração em fonte grande, centralizado, com caixa
semi-transparente — queimado sobre cópia do vídeo silencioso. Os tempos vêm
da estimativa por WPM (ajustável); servem só para leitura, NUNCA como
sincronia final (o áudio humano + Whisper é a fonte da verdade).
"""

from __future__ import annotations

from . import subs as subs_stage
from .scene_contract import SemanticScene, TimelineSpan

TELE_FONT_SIZE = 104
TELE_NEXT_FONT_SIZE = 64
TELE_MARK_FONT_SIZE = 48
# A fonte do teleprompter não vem do perfil de gênero. Ver o comentário
# dentro de `_tele_ass_doc`.
TELE_FAMILY = "DejaVu Sans"
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
        # A fonte do teleprompter é DELETA de propósito, e não uma
        # esquecimento: este arquivo vai para um monitor onde uma pessoa
        # lê o texto ao vivo, não para o vídeo. A identidade editorial do
        # gênero é para quem assiste; itálico serifado num texto que o
        # narrator está lendo em tempo real atrapalha, exatamente como
        # atrapalharia na legenda. É a mesma decisão de
        # `typography.LEGIBILITY_ROLES`, e o teste abaixo impede que
        # alguém "corrija" isso depois.
        f"Style: Teleprompter,{TELE_FAMILY},{TELE_FONT_SIZE},&H00FFFFFF,&H000019FF,"
        f"&H80000000,&HCC000000,1,0,0,0,100,100,0,0,3,2,0,5,120,120,60,1,12\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    body = [f"Dialogue: 0,{subs_stage._fmt_ass_ts(s)},{subs_stage._fmt_ass_ts(e)},"
            f"Teleprompter,,0,0,0,,{text}" for s, e, text in events]
    return head + "\n".join(body) + "\n"


def build_teleprompter_cues(semantic_scenes: tuple[SemanticScene, ...],
                            timeline_spans: tuple[TimelineSpan, ...]
                            ) -> list[tuple[float, float, str, int]]:
    """Espalha blocos de cada cena pela duração tipada correspondente.

    Retorna (início, fim, bloco, id_da_cena). A semântica vem da cena e o
    tempo vem do span; batches desalinhados falham no limite.
    """
    if (any(not isinstance(scene, SemanticScene) for scene in semantic_scenes)
            or any(not isinstance(span, TimelineSpan) for span in timeline_spans)):
        raise TypeError("teleprompter requires SemanticScene and TimelineSpan values")
    scene_ids = tuple(scene.id for scene in semantic_scenes)
    span_ids = tuple(span.scene_id for span in timeline_spans)
    if (not scene_ids or len(scene_ids) != len(set(scene_ids))
            or scene_ids != span_ids):
        raise ValueError("teleprompter scenes and spans are misaligned")
    cues = []
    for scene, span in zip(semantic_scenes, timeline_spans):
        chunks = subs_stage.chunk_words(scene.narration.split(),
                                        TELE_MAX_WORDS, TELE_MAX_CHARS)
        if not chunks:
            continue
        weights = [len(c) + 1 for c in chunks]
        total = sum(weights)
        dur = max(span.end - span.start, span.duration_estimate, 1.0)
        cursor = span.start
        for i, (chunk, w) in enumerate(zip(chunks, weights)):
            share = dur * w / total
            end = span.start + dur if i == len(chunks) - 1 else cursor + share
            cues.append((cursor, end, chunk, scene.id))
            cursor = end
    return cues


def write_teleprompter_ass(semantic_scenes: tuple[SemanticScene, ...],
                           timeline_spans: tuple[TimelineSpan, ...],
                           ass_path: str,
                           width: int, height: int) -> int:
    """Teleprompter de verdade: atual em destaque + próximo embaixo + virada.

    Cada evento mostra o bloco atual (grande, branco, negrito) e o seguinte
    (menor: cinza = continua; ciano + separador = cena nova chegando). Nos
    últimos instantes o atual fica amarelo — o leitor vê a mudança chegando,
    com aviso mais longo no fim de cada cena. Só decoração: texto e tempos
    da narração intactos.
    """
    cues = build_teleprompter_cues(semantic_scenes, timeline_spans)
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
