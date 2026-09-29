"""Narração via TTS com provedores intercambiáveis (PRD §8).

Padrão: edge-tts (voz neural gratuita, sem login — PT-BR masculina).
Fallback: espeak-ng local (offline). O fallback avisa em voz alta no stderr,
nunca silencioso; sem ele o pipeline quebraria sem rede.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from .. import ffmpeg as ff

DEFAULT_EDGE_VOICE = "pt-BR-AntonioNeural"  # masculina, PT-BR

# NOTA: pausas SSML (<break>) foram avaliadas e descartadas — com entrada
# SSML o Edge retorna boundaries dos TOKENS DO MARKUP (speak, voice, break…),
# inutilizando os timestamps. Texto puro + WordBoundary dá palavras reais.


class TTSError(RuntimeError):
    pass


@dataclass
class TTSResult:
    path: str
    duration: float
    provider: str
    voice: str
    speed: int
    words: list[dict] | None = None  # [{text, start, end}] timestamps reais


def available_providers() -> list[str]:
    found = []
    if shutil.which("espeak-ng"):
        found.append("espeak-ng")
    if shutil.which("piper"):
        found.append("piper")
    try:
        __import__("edge_tts")
        found.append("edge-tts")
    except ImportError:
        pass
    return found


def _estimate_wpm(text: str, duration: float) -> int:
    words = len(text.split())
    return round(words / max(duration, 0.1) * 60)


def _synth_edge(text: str, wav_path: str, voice: str, rate: str,
                words_path: str | None = None, metrics=None) -> list[dict]:
    """Voz neural via Edge (grátis, sem login). Requer pacote + internet.

    Texto puro + boundary=WordBoundary: captura timestamps reais por palavra
    (offsets em ticks de 100ns → segundos). Retorna a lista de palavras.
    """
    try:
        import edge_tts
    except ImportError as exc:
        raise TTSError(
            "pacote edge-tts não instalado. Rode `scripts/install.sh` "
            "ou `pip install edge-tts`."
        ) from exc
    import asyncio

    if voice in ("pt-br", "pt-BR", ""):
        voice = DEFAULT_EDGE_VOICE
    mp3_path = wav_path + ".edge.mp3"

    words: list[dict] = []
    audio_parts: list[bytes] = []

    async def _stream() -> None:
        async for chunk in edge_tts.Communicate(
                text, voice, rate=rate, boundary="WordBoundary").stream():
            if chunk.get("type") == "WordBoundary":
                wtext = (chunk.get("text") or "").strip()
                if wtext:
                    words.append({
                        "text": wtext,
                        "start": round((chunk.get("offset") or 0) / 10_000_000, 3),
                        "end": round(((chunk.get("offset") or 0)
                                      + (chunk.get("duration") or 0)) / 10_000_000, 3),
                    })
            elif chunk.get("type") == "audio":
                audio_parts.append(chunk.get("data") or b"")

    try:
        asyncio.run(_stream())
    except Exception as exc:
        raise TTSError(f"edge-tts falhou (voz={voice!r}): {exc}") from exc
    if not audio_parts:
        raise TTSError(f"edge-tts não retornou áudio (voz={voice!r}).")
    if metrics is not None:
        metrics.tts("edge-tts", len(text))
    with open(mp3_path, "wb") as fh:
        for part in audio_parts:
            fh.write(part)
    proc = ff.run([ff.FFMPEG, "-y", "-v", "error", "-i", mp3_path,
                   "-ar", "48000", "-ac", "2", wav_path])
    os.remove(mp3_path)
    if proc.returncode != 0:
        raise TTSError(
            f"conversão do áudio edge-tts falhou: {proc.stderr.strip()}")
    if words_path:
        import json
        with open(words_path, "w", encoding="utf-8") as fh:
            json.dump(words, fh, ensure_ascii=False, indent=1)
    return words


def _synth_espeak(text: str, wav_path: str, voice: str, speed: int,
                  metrics=None) -> None:
    txt_path = wav_path + ".txt"
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    proc = subprocess.run(
        ["espeak-ng", "-v", voice, "-s", str(speed), "-w", wav_path, "-f", txt_path],
        capture_output=True, text=True,
    )
    os.remove(txt_path)
    if metrics is not None:
        metrics.tts("espeak-ng", len(text))
    if proc.returncode != 0:
        raise TTSError(
            f"espeak-ng falhou (voz={voice!r}): {proc.stderr.strip() or proc.stdout.strip()}. "
            "Rode `video-gen doctor`."
        )


def synthesize(text: str, wav_path: str, provider: str, voice: str,
               speed: int, target_duration: float,
               words_path: str | None = None, metrics=None) -> TTSResult:
    if provider not in ("edge-tts", "espeak-ng", "auto"):
        raise TTSError(
            f"provedor TTS {provider!r} desconhecido "
            f"(disponíveis: {available_providers() or ['nenhum']})."
        )
    ff.require_tools()
    want_edge = provider in ("edge-tts", "auto")

    if want_edge:
        try:
            return _synthesize_edge(text, wav_path, voice, target_duration,
                                    words_path, metrics)
        except TTSError as exc:
            if shutil.which("espeak-ng") is None:
                raise TTSError(
                    f"{exc} E espeak-ng não está instalado — sem fallback. "
                    "Rode `scripts/install.sh`."
                ) from exc
            print(f"AVISO: {exc} Usando espeak-ng local como fallback.",
                  file=sys.stderr)
            # Vozes neurais ("pt-BR-AntonioNeural") não existem no espeak:
            # fallback usa o padrão local pt-br.
            voice, speed = "pt-br", 170
    if shutil.which("espeak-ng") is None:
        raise TTSError("espeak-ng não encontrado. Rode `scripts/install.sh`.")
    return _synthesize_espeak(text, wav_path, voice, speed, target_duration,
                              metrics)


def _synthesize_edge(text: str, wav_path: str, voice: str,
                     target_duration: float,
                     words_path: str | None = None, metrics=None) -> TTSResult:
    # Ritmo sempre natural: a duração final é consequência do roteiro e do
    # áudio — `target_duration` é só meta informativa (nunca altera a fala).
    words = _synth_edge(text, wav_path, voice, "+0%", words_path, metrics)
    duration = ff.probe_duration(wav_path)

    return TTSResult(path=wav_path, duration=duration, provider="edge-tts",
                     voice=voice, speed=_estimate_wpm(text, duration),
                     words=words)


def _synthesize_espeak(text: str, wav_path: str, voice: str,
                       speed: int, target_duration: float,
                       metrics=None) -> TTSResult:
    # Idem: sem segunda passada acelerada — ritmo natural, sem corte.
    _synth_espeak(text, wav_path, voice, speed, metrics)
    duration = ff.probe_duration(wav_path)

    return TTSResult(path=wav_path, duration=duration,
                     provider="espeak-ng", voice=voice, speed=speed)
