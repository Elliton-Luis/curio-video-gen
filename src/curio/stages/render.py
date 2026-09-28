"""Montagem de vídeo via FFmpeg (PRD §10, §11).

Primitivas: segmentos por cena (imagem com Ken Burns, vídeo com crop 9:16,
fallback em gradiente), concat, queima de legendas + áudio. Encoder:
VA-API > QSV > libx264 (auto-detect).
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


def _background_src(cfg: CurioConfig) -> str:
    w, h, fps = cfg.width, cfg.height, cfg.fps
    grad = (
        f"gradients=s={w}x{h}:c0=0x141433:c1=0x2b1055:"
        f"c2=0x0f2027:c3=0x203a43:n=4:speed=0.06,format=yuv420p"
    )
    probe = ff.run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi",
                    "-i", grad, "-frames:v", "1", "-f", "null", "-"])
    if probe.returncode == 0:
        return grad
    return f"color=c=0x141433:s={w}x{h}:r={fps},format=yuv420p"


def _video_codec_args(cfg: CurioConfig) -> tuple[str, str, list[str]]:
    backend, encoder = ff.pick_encoder(cfg.render_backend)
    if backend == "vaapi":
        return backend, encoder, ["-c:v", "h264_vaapi", "-qp", "22"]
    if backend == "qsv":
        return backend, encoder, ["-c:v", "h264_qsv", "-global_quality", "23"]
    return backend, encoder, ["-c:v", "libx264", "-preset", "veryfast",
                              "-crf", "20", "-pix_fmt", "yuv420p"]


def _hw_upload(vf: list[str], cmd: list[str], cfg: CurioConfig,
               backend: str) -> None:
    """VA-API exige frames em hardware: upload no fim da cadeia de filtros."""
    if backend == "vaapi":
        from ..ffmpeg import vaapi_device
        vf.extend(["format=nv12", "hwupload"])
        cmd += ["-vaapi_device", vaapi_device() or "/dev/dri/renderD128"]


def _check(proc, what: str) -> None:
    if proc.returncode != 0:
        raise RenderError(
            f"ffmpeg ({what}) falhou: {(proc.stderr or proc.stdout).strip()[-2000:]}"
        )


def render_image_segment(img_path: str, duration: float, out_path: str,
                         cfg: CurioConfig, variant: int = 0) -> str:
    """Foto com Ken Burns discreto (zoom-in ou pan), sem distorção."""
    w, h, fps = cfg.width, cfg.height, cfg.fps
    frames = max(1, round(duration * fps))
    base = (f"scale=2160:3840:force_original_aspect_ratio=increase:"
            f"out_range=mpeg,crop=2160:3840")
    if variant % 2 == 0:  # zoom-in central lento
        zb = f"zoompan=z='min(1.0+0.0006*on,{1.0 + 0.0006 * frames:.4f})'"
    else:  # pan horizontal lento
        zb = (f"zoompan=z=1.08:x='(iw-iw/zoom)*on/{frames}':"
              f"y='ih/2-(ih/zoom/2)'")
    vf = (f"{base},{zb}:d={frames}:s={w}x{h}:fps={fps},format=yuv420p")
    backend, _, vargs = _video_codec_args(cfg)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-loop", "1", "-framerate", str(fps), "-i", img_path]
    vf_list = [vf]
    _hw_upload(vf_list, cmd, cfg, backend)
    proc = ff.run(cmd + ["-vf", ",".join(vf_list), "-frames:v", str(frames),
                         "-r", str(fps)] + vargs + ["-an", out_path])
    _check(proc, "ken-burns")
    return out_path


def render_video_segment(vid_path: str, duration: float, out_path: str,
                         cfg: CurioConfig) -> str:
    """Trecho central de vídeo com crop 9:16, proporção preservada."""
    w, h, fps = cfg.width, cfg.height, cfg.fps
    vdur = ff.probe_duration(vid_path)
    ss = max(0.0, (vdur - duration) / 2) if vdur > duration else 0.0
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
          f"crop={w}:{h},fps={fps},format=yuv420p")
    backend, _, vargs = _video_codec_args(cfg)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", str(round(ss, 2)), "-i", vid_path]
    vf_list = [vf]
    _hw_upload(vf_list, cmd, cfg, backend)
    proc = ff.run(cmd + ["-vf", ",".join(vf_list), "-t", str(duration),
                         "-r", str(fps)] + vargs + ["-an", out_path])
    _check(proc, "video-cover")
    return out_path


def render_fallback_segment(duration: float, out_path: str, cfg: CurioConfig,
                            title_lines: list[str]) -> str:
    """Gradiente + título (mesma identidade do MVP) quando falta mídia."""
    w, h, fps = cfg.width, cfg.height, cfg.fps
    vf = []
    fontfile = ff.find_font_bold()
    if fontfile:
        for i, line in enumerate(title_lines[:2]):
            safe = line.replace(":", "\\:").replace("'", "")
            vf.append(
                f"drawtext=fontfile='{fontfile}':text='{safe}':"
                f"fontsize=54:fontcolor=white:borderw=2:bordercolor=0x000000AA:"
                f"x=(w-text_w)/2:y={150 + i * 76}"
            )
    vf.append("format=yuv420p")
    backend, _, vargs = _video_codec_args(cfg)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", _background_src(cfg)]
    _hw_upload(vf, cmd, cfg, backend)
    proc = ff.run(cmd + ["-vf", ",".join(vf), "-t", str(duration),
                         "-r", str(fps)] + vargs + ["-an", out_path])
    _check(proc, "fallback")
    return out_path


def concat_copy(paths: list[str], out_path: str) -> str:
    """Concatena segmentos idênticos sem re-encode."""
    import os
    list_path = out_path + ".files.txt"
    with open(list_path, "w", encoding="utf-8") as fh:
        for p in paths:
            # Absoluto: o demuxer concat resolve relativo ao .txt, não ao CWD.
            fh.write(f"file '{os.path.abspath(p)}'\n")
    proc = ff.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                   "-i", list_path, "-c", "copy", out_path])
    _check(proc, "concat")
    return out_path


def burn_final(silent_path: str, subs_ass: str | None, wav_path: str | None,
               out_path: str, cfg: CurioConfig, total: float) -> dict:
    """silent + legendas queimadas + áudio → MP4 final (um encode só)."""
    ff.require_tools()
    backend, encoder, vargs = _video_codec_args(cfg)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", silent_path]
    vf = []
    if subs_ass:
        vf.append(f"subtitles={ff.escape_sub_path(subs_ass)}")
    if backend == "vaapi":
        from ..ffmpeg import vaapi_device
        vf.extend(["format=nv12", "hwupload"])
        cmd += ["-vaapi_device", vaapi_device() or "/dev/dri/renderD128"]
    if wav_path:
        cmd += ["-i", wav_path, "-map", "0:v", "-map", "1:a"]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-r", str(cfg.fps), "-t", str(total)] + vargs
    if wav_path:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                "-af", f"aresample=48000,apad=whole_dur={total}"]
    cmd += ["-movflags", "+faststart", out_path]
    _check(ff.run(cmd), encoder)
    actual = ff.probe_duration(out_path)
    return {"backend": backend, "encoder": encoder,
            "duration": actual, "path": out_path}
