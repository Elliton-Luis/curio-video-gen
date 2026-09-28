"""Narração via TTS com provedores intercambiáveis (PRD §8).

Padrão MVP: espeak-ng local (gratuito, offline, voz pt-br).
`piper` e `edge-tts` são detectados se instalados, mas nunca obrigatórios.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from .. import ffmpeg as ff


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
    if provider not in ("espeak-ng", "auto"):
        raise TTSError(
            f"provedor TTS {provider!r} indisponível no MVP "
            f"(disponíveis: {available_providers() or ['nenhum — instale espeak-ng']})."
        )
    if shutil.which("espeak-ng") is None:
        raise TTSError("espeak-ng não encontrado. Rode `scripts/install.sh`.")
    ff.require_tools()

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
