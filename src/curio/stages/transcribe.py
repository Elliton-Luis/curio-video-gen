"""Transcrição local de áudio humano via faster-whisper (§22).

O áudio real é a fonte da verdade: word timestamps do Whisper viram as
legendas finais. Modelo `base` em CPU/int8: rápido o bastante para ~45 s.
"""

from __future__ import annotations

import difflib
import re


class TranscribeError(RuntimeError):
    pass


def align_to_script(text: str, words: list[dict]) -> list[dict]:
    """Keep script spelling and punctuation on audio-derived word times.

    Recognition may merge short words or miss proper names. Preserve matched
    timestamps; estimate only words in the small unmatched intervals.
    """
    expected = text.split()
    key = lambda value: re.sub(r"[^\w]", "", value.casefold())
    match = difflib.SequenceMatcher(
        None, [key(token) for token in expected],
        [key(str(word["text"])) for word in words], autojunk=False)
    if match.ratio() < 0.85:
        raise TranscribeError("transcrição diverge muito do roteiro; sincronização não confiável")
    aligned = []
    for _tag, i, j, k, l in match.get_opcodes():
        tokens = expected[i:j]
        heard = words[k:l]
        if not tokens:
            continue
        if len(tokens) == len(heard):
            aligned.extend({**word, "text": token}
                           for token, word in zip(tokens, heard))
            continue
        if heard:
            start, end = float(heard[0]["start"]), float(heard[-1]["end"])
        else:
            start = float(aligned[-1]["end"]) if aligned else 0.0
            end = float(words[k]["start"]) if k < len(words) else start
            if end - start < 0.03 * len(tokens) and aligned:
                previous = aligned[-1]
                reserved = min(0.08 * len(tokens),
                               (float(previous["end"]) - float(previous["start"])) / 2)
                start -= reserved
                previous["end"] = start
        if end <= start:
            raise TranscribeError("palavra do roteiro sem intervalo de áudio")
        weight = sum(max(1, len(key(token))) for token in tokens)
        cursor = start
        for token in tokens:
            stop = cursor + (end - start) * max(1, len(key(token))) / weight
            aligned.append({"text": token, "start": cursor, "end": stop})
            cursor = stop
    return aligned


def transcribe(audio_path: str, model_name: str = "base",
               language: str = "pt", metrics=None) -> list[dict]:
    """Retorna palavras [{text, start, end}] com timestamps reais."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscribeError(
            "faster-whisper não instalado. Rode `scripts/install.sh` "
            "ou `pip install faster-whisper`."
        ) from exc
    try:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(audio_path, language=language,
                                           word_timestamps=True)
        words = []
        for seg in segments:
            for w in (seg.words or []):
                text = (w.word or "").strip()
                if text:
                    words.append({"text": text,
                                  "start": round(w.start, 3),
                                  "end": round(w.end, 3)})
    except Exception as exc:
        raise TranscribeError(f"transcrição falhou: {exc}") from exc
    if not words:
        raise TranscribeError("transcrição vazia — áudio sem fala detectada?")
    if metrics is not None:
        metrics.whisper(model_name)
    return words
