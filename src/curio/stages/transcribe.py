"""Transcrição local de áudio humano via faster-whisper (§22).

O áudio real é a fonte da verdade: word timestamps do Whisper viram as
legendas finais. Modelo `base` em CPU/int8: rápido o bastante para ~45 s.
"""

from __future__ import annotations


class TranscribeError(RuntimeError):
    pass


def transcribe(audio_path: str, model_name: str = "base",
               language: str = "pt") -> list[dict]:
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
    return words
