"""Utilidades compartilhadas de FFmpeg/ffprobe e detecção de hardware (PRD §11)."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


class FFMpegError(RuntimeError):
    pass


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise FFMpegError(
            f"executável não encontrado: {cmd[0]}. Rode `scripts/install.sh`."
        ) from exc


def require_tools() -> None:
    if shutil.which("ffmpeg") is None:
        raise FFMpegError("ffmpeg não encontrado no PATH. Rode `scripts/install.sh`.")
    if shutil.which("ffprobe") is None:
        raise FFMpegError("ffprobe não encontrado no PATH. Rode `scripts/install.sh`.")


def probe_duration(path: str) -> float:
    proc = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                "-of", "json", path])
    if proc.returncode != 0:
        raise FFMpegError(f"ffprobe falhou em {path}: {proc.stderr.strip()}")
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise FFMpegError(f"não foi possível ler duração de {path}") from exc


def has_encoder(name: str) -> bool:
    proc = run([FFMPEG, "-hide_banner", "-h", f"encoder={name}"])
    return proc.returncode == 0


def vaapi_device() -> str | None:
    devs = sorted(glob.glob("/dev/dri/renderD*"))
    if not devs:
        return None
    # Valida com um encode real de 1 frame em vez de confiar só no vainfo.
    probe = run([FFMPEG, "-hide_banner", "-v", "error",
                 "-f", "lavfi", "-i", "color=s=64x64:d=0.1",
                 "-vaapi_device", devs[0],
                 "-vf", "format=nv12,hwupload",
                 "-c:v", "h264_vaapi", "-f", "null", "-"])
    return devs[0] if probe.returncode == 0 else None


def pick_encoder(prefer: str = "auto") -> tuple[str, str]:
    """Retorna (backend, encoder). Nunca assume backend: detecta e cai para CPU."""
    prefer = prefer.lower()
    vaapi = vaapi_device() if prefer in ("auto", "vaapi") else None
    if prefer == "vaapi" and not vaapi:
        raise FFMpegError("backend vaapi solicitado, mas nenhum dispositivo VA-API funcional.")
    if vaapi and prefer in ("auto", "vaapi"):
        return "vaapi", "h264_vaapi"
    if prefer in ("auto", "qsv") and has_encoder("h264_qsv"):
        # QSV só é útil com driver Intel; valida de forma barata.
        probe = run([FFMPEG, "-hide_banner", "-v", "error",
                     "-f", "lavfi", "-i", "color=s=64x64:d=0.1",
                     "-c:v", "h264_qsv", "-f", "null", "-"])
        if probe.returncode == 0:
            return "qsv", "h264_qsv"
        if prefer == "qsv":
            raise FFMpegError("backend qsv solicitado, mas o encode de teste falhou.")
    if prefer == "cpu" or prefer == "auto":
        return "cpu", "libx264"
    raise FFMpegError(f"backend de render desconhecido: {prefer!r} (use auto|vaapi|qsv|cpu)")


_FONT_CANDIDATES = [
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def find_font_bold() -> str | None:
    for cand in _FONT_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    return None


def escape_sub_path(path: str) -> str:
    # Filtro `subtitles` separa opções por `:` — escapa caminho absoluto.
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'").replace(" ", "\\ ")
