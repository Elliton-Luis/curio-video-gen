"""Legendas sincronizadas a partir da narração (PRD §9).

O TTS do MVP não fornece timestamps por palavra, então os tempos são
distribuídos proporcionalmente ao tamanho de cada bloco — sincronização
"suficientemente precisa" sem retranscrever o áudio.

Saída dupla a partir dos mesmos cues (mesma sincronia):
- `.srt`: artefato legível/portátil;
- `.ass`: o que o FFmpeg realmente queima no vídeo, com PlayRes, fonte,
  posição e margens explícitos (o filtro `subtitles` sem PlayRes usa
  384x288 e estoura o tamanho/posição — bug encontrado em teste visual).
"""

from __future__ import annotations

import re


def _words(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def _sentences(text: str) -> list[str]:
    """Quebra em frases para respeitar pausas naturais da narração."""
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p for p in parts if p]


def chunk_words(words: list[str], max_words: int = 5, max_chars: int = 36) -> list[str]:
    """Blocos curtos (≤2 linhas na tela): poucas palavras, limite de chars."""
    chunks, cur, cur_len = [], [], 0
    for word in words:
        extra = len(word) + (1 if cur else 0)
        if cur and (len(cur) >= max_words or cur_len + extra > max_chars):
            chunks.append(" ".join(cur))
            cur, cur_len = [], 0
        cur.append(word)
        cur_len += len(word) + 1
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def _fmt_ts(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_cues(text: str, total_duration: float,
               lead: float = 0.15) -> list[tuple[float, float, str]]:
    """Divide em cues curtos com tempos proporcionais. Coração da sincronia."""
    words = _words(text)
    if not words:
        raise ValueError("roteiro vazio — nada para legendar")
    # Frases primeiro (quebras naturais), depois limite de palavras/chars.
    chunks = [c for s in _sentences(text) for c in chunk_words(s.split())]
    if not chunks:
        chunks = chunk_words(words)
    weights = [sum(len(w) + 1 for w in c.split()) for c in chunks]
    total_w = sum(weights)
    usable = max(0.5, total_duration - lead)
    cues, cursor = [], lead
    for i, (cue, w) in enumerate(zip(chunks, weights)):
        share = usable * w / total_w
        start = cursor
        end = total_duration if i == len(chunks) - 1 else cursor + share
        if end - start < 1.0 and i != len(chunks) - 1:
            end = min(total_duration, start + 1.0)
        cues.append((start, end, cue))
        cursor = end
    return cues


def cues_to_srt(cues: list[tuple[float, float, str]]) -> str:
    lines = []
    for i, (start, end, cue) in enumerate(cues, 1):
        lines.append(f"{i}\n{_fmt_ts(start)} --> {_fmt_ts(end)}\n{cue}\n")
    return "\n".join(lines) + "\n"


def build_srt(text: str, total_duration: float, lead: float = 0.15) -> str:
    return cues_to_srt(build_cues(text, total_duration, lead))


def _fmt_ass_ts(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def cues_to_ass(cues: list[tuple[float, float, str]], width: int, height: int,
                font_size: int, margin_v: int) -> str:
    """ASS com PlayRes = resolução real: fonte/margem em pixels de verdade."""
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
        f"Style: Default,DejaVu Sans,{font_size},&H00FFFFFF,&H000019FF,"
        f"&H80000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,60,60,{margin_v},1\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    body = []
    for start, end, cue in cues:
        safe = cue.replace("{", "").replace("}", "").replace("\n", " ")
        body.append(f"Dialogue: 0,{_fmt_ass_ts(start)},{_fmt_ass_ts(end)},"
                    f"Default,,0,0,0,,{safe}")
    return head + "\n".join(body) + "\n"


def write_srt(text: str, total_duration: float, srt_path: str) -> tuple[str, int]:
    srt = build_srt(text, total_duration)
    with open(srt_path, "w", encoding="utf-8") as fh:
        fh.write(srt)
    return srt_path, srt.count("-->")


def write_subtitles(text: str, total_duration: float, srt_path: str,
                    ass_path: str, width: int, height: int,
                    base_font_size: int, margin_v: int) -> int:
    """Gera SRT + ASS a partir dos mesmos cues. Retorna nº de blocos.

    A fonte do ASS é escalada pela altura (base calibrada para 1920),
    em pixels reais — PlayRes do ASS = resolução do vídeo.
    """
    font_size = max(20, round(base_font_size * height / 1920))
    cues = build_cues(text, total_duration)
    with open(srt_path, "w", encoding="utf-8") as fh:
        fh.write(cues_to_srt(cues))
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(cues_to_ass(cues, width, height, font_size, margin_v))
    return len(cues)
