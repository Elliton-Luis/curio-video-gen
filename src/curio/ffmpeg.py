"""Utilidades compartilhadas de FFmpeg/ffprobe e detecção de hardware (PRD §11)."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys

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


def _render_nodes() -> list[str]:
    """Nós de render DRI ordenados (estável, sem sorte)."""
    return sorted(glob.glob("/dev/dri/renderD*"))


def _node_vendor(node: str) -> str:
    """Vendor PCI do nó DRI (`0x8086` = Intel) ou '' se ilegível."""
    base = os.path.basename(node)
    for cand in (f"/sys/class/drm/{base}/device/vendor",
                 f"/sys/class/drm/{base.replace('renderD', 'card')}/device/vendor"):
        try:
            with open(cand, encoding="utf-8") as fh:
                return fh.read().strip().lower()
        except OSError:
            continue
    return ""


def intel_render_node() -> str | None:
    """Nó de render de GPU Intel (ex.: Arc B580) ou None se ausente."""
    for node in _render_nodes():
        if _node_vendor(node) == "0x8086":
            return node
    return None


def _vaapi_probe(device: str, encoder: str, width: int = 1080,
                 height: int = 1920) -> bool:
    """Encode real de 1 frame no formato do projeto (não confia só no vainfo)."""
    probe = run([FFMPEG, "-hide_banner", "-v", "error",
                 "-f", "lavfi", "-i",
                 f"color=s={width}x{height}:d=0.1",
                 "-vaapi_device", device,
                 "-vf", "format=nv12,hwupload",
                 "-c:v", encoder, "-f", "null", "-"])
    return probe.returncode == 0


def vaapi_device() -> str | None:
    devs = _render_nodes()
    if not devs:
        return None
    # Prefere GPU Intel (Arc/discreta) em vez de depender da ordem do glob.
    ordered = sorted(devs, key=lambda d: 0 if _node_vendor(d) == "0x8086" else 1)
    # Valida com um encode real de 1 frame em vez de confiar só no vainfo.
    probe = run([FFMPEG, "-hide_banner", "-v", "error",
                 "-f", "lavfi", "-i", "color=s=64x64:d=0.1",
                 "-vaapi_device", ordered[0],
                 "-vf", "format=nv12,hwupload",
                 "-c:v", "h264_vaapi", "-f", "null", "-"])
    return ordered[0] if probe.returncode == 0 else None


# Encoders VA-API testados no nó Intel, do mais compatível ao alternativo.
# (H.264/HEVC VA-API nem sempre têm entrypoint de encode no iHD — ex.: Arc
# com driver xe expõe só AV1; o probe real decide, sem chute.)
_INTEL_VAAPI_ENCODERS = ("av1_vaapi", "hevc_vaapi", "h264_vaapi")


def intel_hw_encoder() -> tuple[str, str] | None:
    """(nó Intel, encoder VA-API funcional) ou None.

    Testa no formato real do projeto (1080x1920): o probe de 64x64 aprova
    encoders que falham na resolução final.
    """
    node = intel_render_node()
    if node is not None:
        for encoder in _INTEL_VAAPI_ENCODERS:
            if has_encoder(encoder) and _vaapi_probe(node, encoder):
                return node, encoder
    return None


def qsv_working() -> bool:
    """QSV validado com encode real (barato)."""
    if not has_encoder("h264_qsv"):
        return False
    probe = run([FFMPEG, "-hide_banner", "-v", "error",
                 "-f", "lavfi", "-i", "color=s=64x64:d=0.1",
                 "-c:v", "h264_qsv", "-f", "null", "-"])
    return probe.returncode == 0


def pick_encoder(prefer: str = "auto") -> tuple[str, str]:
    """Retorna (backend, encoder). Nunca assume backend: detecta e cai para CPU.

    `arc` = GPU Intel primeiro (Arc B580 via VA-API/AV1, depois QSV);
    sem Intel funcional, cai para CPU com o mesmo contrato dos demais.
    """
    prefer = (prefer or "auto").lower()
    if prefer == "arc":
        hw = intel_hw_encoder()
        if hw is not None:
            _node, encoder = hw
            return "arc", encoder
        if qsv_working():
            return "arc", "h264_qsv"
        print("AVISO: backend 'arc' sem aceleração Intel funcional — usando CPU.",
              file=sys.stderr)
        return "cpu", "libx264"
    vaapi = vaapi_device() if prefer in ("auto", "vaapi") else None
    if prefer == "vaapi" and not vaapi:
        raise FFMpegError("backend vaapi solicitado, mas nenhum dispositivo VA-API funcional.")
    if vaapi and prefer in ("auto", "vaapi"):
        return "vaapi", "h264_vaapi"
    if prefer in ("auto", "qsv") and qsv_working():
        return "qsv", "h264_qsv"
    if prefer == "qsv":
        raise FFMpegError("backend qsv solicitado, mas o encode de teste falhou.")
    if prefer == "cpu" or prefer == "auto":
        return "cpu", "libx264"
    raise FFMpegError(f"backend de render desconhecido: {prefer!r} (use auto|arc|vaapi|qsv|cpu)")


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
