"""Montagem do vídeo final via FFmpeg (PRD §10, §11).

Fundo em gradiente animado (lavfi, sem downloads) + título + legendas
queimadas (libass) + narração. Encoder: VA-API > QSV > libx264 (auto-detect).
"""

from __future__ import annotations

from .. import ffmpeg as ff
from ..config import CurioConfig


class RenderError(RuntimeError):
    pass


def _wrap_title(idea: str, width: int = 26) -> list[str]:
    words, lines, cur = idea.strip().split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if len(trial) > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
        if len(lines) == 2:
            break
    if cur and len(lines) < 2:
        lines.append(cur)
    if len(lines) == 2 and len(idea) > sum(len(line) for line in lines) + 2:
        lines[1] = lines[1][: width - 1] + "…"
    return [line.upper() for line in lines][:2]


def render_video(wav_path: str, srt_path: str, mp4_path: str,
                 idea: str, audio_duration: float, cfg: CurioConfig) -> dict:
    ff.require_tools()
    backend, encoder = ff.pick_encoder(cfg.render_backend)
    total = round(audio_duration + 0.8, 2)
    w, h, fps = cfg.width, cfg.height, cfg.fps

    # Gradiente animado; cai para cor chapada se a source `gradients` faltar.
    grad = (
        f"gradients=s={w}x{h}:c0=0x141433:c1=0x2b1055:"
        f"c2=0x0f2027:c3=0x203a43:n=4:speed=0.06,format=yuv420p"
    )
    probe = ff.run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi",
                    "-i", grad, "-frames:v", "1", "-f", "null", "-"])
    bg = grad if probe.returncode == 0 else f"color=c=0x141433:s={w}x{h}:r={fps},format=yuv420p"

    vf: list[str] = []
    fontfile = ff.find_font_bold()
    if fontfile:
        for i, line in enumerate(_wrap_title(idea)):
            safe = line.replace(":", "\\:").replace("'", "")
            vf.append(
                f"drawtext=fontfile='{fontfile}':text='{safe}':"
                f"fontsize=54:fontcolor=white:borderw=2:bordercolor=0x000000AA:"
                f"x=(w-text_w)/2:y={150 + i * 76}"
            )
    vf.append(
        f"subtitles={ff.escape_sub_path(srt_path)}:"
        f"force_style='FontSize={cfg.sub_font_size},PrimaryColour=&HFFFFFF,"
        f"OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,"
        f"Alignment=2,MarginV={cfg.sub_margin_v}'"
    )

    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", bg,
           "-i", wav_path,
           "-map", "0:v", "-map", "1:a",
           "-t", str(total)]
    if backend == "vaapi":
        from ..ffmpeg import vaapi_device
        vf.extend(["format=nv12", "hwupload"])
        cmd += ["-vaapi_device", vaapi_device() or "/dev/dri/renderD128"]
    vf_str = ",".join(vf)
    cmd += ["-vf", vf_str, "-r", str(fps)]
    if backend == "vaapi":
        cmd += ["-c:v", "h264_vaapi", "-qp", "22"]
    elif backend == "qsv":
        cmd += ["-c:v", "h264_qsv", "-global_quality", "23"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-af", f"aresample=48000,apad=whole_dur={total}",
            "-movflags", "+faststart", mp4_path]

    proc = ff.run(cmd)
    if proc.returncode != 0:
        raise RenderError(
            f"ffmpeg ({encoder}) falhou: {(proc.stderr or proc.stdout).strip()[-2000:]}"
        )
    actual = ff.probe_duration(mp4_path)
    return {"backend": backend, "encoder": encoder,
            "duration": actual, "path": mp4_path}
