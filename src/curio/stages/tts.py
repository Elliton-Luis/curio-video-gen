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


class TTSError(RuntimeError):
    pass


@dataclass
class TTSResult:
    path: str
    duration: float
    provider: str
    voice: str
    speed: int


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


def _synth_edge(text: str, wav_path: str, voice: str, rate: str) -> None:
    """Voz neural via Edge (grátis, sem login). Requer pacote + internet."""
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

    async def _save() -> None:
        await edge_tts.Communicate(text, voice, rate=rate).save(mp3_path)

    try:
        asyncio.run(_save())
    except Exception as exc:
        raise TTSError(f"edge-tts falhou (voz={voice!r}): {exc}") from exc
    proc = ff.run([ff.FFMPEG, "-y", "-v", "error", "-i", mp3_path,
                   "-ar", "48000", "-ac", "2", wav_path])
    os.remove(mp3_path)
    if proc.returncode != 0:
        raise TTSError(
            f"conversão do áudio edge-tts falhou: {proc.stderr.strip()}")


def _synth_espeak(text: str, wav_path: str, voice: str, speed: int) -> None:
    txt_path = wav_path + ".txt"
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    proc = subprocess.run(
        ["espeak-ng", "-v", voice, "-s", str(speed), "-w", wav_path, "-f", txt_path],
        capture_output=True, text=True,
    )
    os.remove(txt_path)
    if proc.returncode != 0:
        raise TTSError(
            f"espeak-ng falhou (voz={voice!r}): {proc.stderr.strip() or proc.stdout.strip()}. "
            "Rode `video-gen doctor`."
        )


def synthesize(text: str, wav_path: str, provider: str, voice: str,
               speed: int, target_duration: float) -> TTSResult:
    if provider not in ("edge-tts", "espeak-ng", "auto"):
        raise TTSError(
            f"provedor TTS {provider!r} desconhecido "
            f"(disponíveis: {available_providers() or ['nenhum']})."
        )
    ff.require_tools()
    want_edge = provider in ("edge-tts", "auto")

    if want_edge:
        try:
            return _synthesize_edge(text, wav_path, voice, target_duration)
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
    return _synthesize_espeak(text, wav_path, voice, speed, target_duration)


def _synthesize_edge(text: str, wav_path: str, voice: str,
                     target_duration: float) -> TTSResult:
    _synth_edge(text, wav_path, voice, "+0%")
    duration = ff.probe_duration(wav_path)

    # Uma correção de ritmo (a duração-alvo é meta, não corte — §5).
    if target_duration > 0:
        ratio = duration / target_duration
        if ratio < 0.85 or ratio > 1.15:
            pct = max(-30, min(30, round((ratio - 1) * 100)))
            rate = f"{pct:+d}%"
            _synth_edge(text, wav_path, voice, rate)
            duration = ff.probe_duration(wav_path)
            voice = f"{voice} ({rate})"

    return TTSResult(path=wav_path, duration=duration, provider="edge-tts",
                     voice=voice, speed=_estimate_wpm(text, duration))


def _synthesize_espeak(text: str, wav_path: str, voice: str,
                       speed: int, target_duration: float) -> TTSResult:
    _synth_espeak(text, wav_path, voice, speed)
    duration = ff.probe_duration(wav_path)

    # Uma tentativa de correção de ritmo: se fugir >15% da meta, ajusta a
    # velocidade e sintetiza de novo (a duração-alvo é meta, não corte — §5).
    if target_duration > 0:
        ratio = duration / target_duration
        if ratio < 0.85 or ratio > 1.15:
            fixed = max(120, min(220, round(speed * ratio)))
            _synth_espeak(text, wav_path, voice, fixed)
            duration = ff.probe_duration(wav_path)
            speed = fixed

    return TTSResult(path=wav_path, duration=duration,
                     provider="espeak-ng", voice=voice, speed=speed)
