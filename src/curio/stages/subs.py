"""Legendas sincronizadas a partir da narração (PRD §9).

O TTS do MVP não fornece timestamps por palavra, então os tempos são
distribuídos proporcionalmente ao tamanho de cada bloco — sincronização
"suficientemente precisa" sem retranscrever o áudio.
"""

from __future__ import annotations

import re


def _words(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def chunk_words(words: list[str], max_words: int = 7, max_chars: int = 42) -> list[str]:
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


def build_srt(text: str, total_duration: float, lead: float = 0.15) -> str:
    words = _words(text)
    if not words:
        raise ValueError("roteiro vazio — nada para legendar")
    chunks = chunk_words(words)
    weights = [sum(len(w) + 1 for w in c.split()) for c in chunks]
    total_w = sum(weights)
    usable = max(0.5, total_duration - lead)
    lines = []
    cursor = lead
    for i, (cue, w) in enumerate(zip(chunks, weights)):
        share = usable * w / total_w
        start = cursor
        end = total_duration if i == len(chunks) - 1 else cursor + share
        if end - start < 1.0 and i != len(chunks) - 1:
            end = min(total_duration, start + 1.0)
        lines.append(f"{i + 1}\n{_fmt_ts(start)} --> {_fmt_ts(end)}\n{cue}\n")
        cursor = end
    return "\n".join(lines) + "\n"


def write_srt(text: str, total_duration: float, srt_path: str) -> tuple[str, int]:
    srt = build_srt(text, total_duration)
    with open(srt_path, "w", encoding="utf-8") as fh:
        fh.write(srt)
    return srt_path, srt.count("-->")
