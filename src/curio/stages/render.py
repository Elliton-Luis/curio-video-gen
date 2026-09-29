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


def render_collage_segment(images: list[dict], duration: float,
                           out_path: str, cfg: CurioConfig,
                           variant: int = 0) -> str:
    """Cena-álbum: base em tela cheia + fotos entrando por cima com sobreposição.

    `images` segue o plano de `stages.visual` (ordem, início/duração na
    cena, transição, rotação, dx/dy). A imagem 0 é a base (Ken Burns sutil);
    as seguintes entram como cartão-fotografia (borda branca, leve rotação
    e deslocamento) e permanecem por cima até o fim da cena — pilha de
    álbum, nunca slides. Cartões ficam na metade superior: os ~360 px
    inferiores são reserva das legendas. Com 0–1 imagem, delega para o
    comportamento clássico (fallback ou Ken Burns).
    """
    import math
    import os as _os
    valid = [im for im in images
             if im.get("local_path") and _os.path.isfile(im["local_path"])]
    if not valid:
        return render_fallback_segment(
            duration, out_path, cfg, _wrap_title("curio"))
    if len(valid) == 1 or valid[0].get("kind") == "video":
        only = valid[0]
        if only.get("kind") == "video":
            return render_video_segment(only["local_path"], duration,
                                        out_path, cfg)
        return render_image_segment(only["local_path"], duration, out_path,
                                    cfg, variant)
    w, h, fps = cfg.width, cfg.height, cfg.fps
    duration = max(0.5, float(duration))
    frames = max(1, round(duration * fps))
    card_w = max(320, round(w * 0.85))

    base_scale = ("scale=2160:3840:force_original_aspect_ratio=increase:"
                  "out_range=mpeg,crop=2160:3840")
    if variant % 2 == 0:
        zb = f"zoompan=z='min(1.0+0.0006*on,{1.0 + 0.0006 * frames:.4f})'"
    else:
        zb = (f"zoompan=z=1.08:x='(iw-iw/zoom)*on/{frames}':"
              f"y='ih/2-(ih/zoom/2)'")
    parts = [f"[0:v]{base_scale},{zb}:d={frames}:s={w}x{h}:fps={fps},"
             f"format=yuv420p[base]"]
    for i, im in enumerate(valid[1:], 1):
        rot = float(im.get("rotation_deg", 0.0)) * math.pi / 180
        start = float(im.get("start", 0.0))
        entry = max(0.3, float(im.get("entry_dur", 0.6)))
        end_e = start + entry
        fade_d = min(0.4, max(0.2, entry * 0.5))
        tr = im.get("transition", "fade")
        base_card = (f"scale={card_w}:1000:force_original_aspect_ratio=decrease,"
                     f"pad=iw+28:ih+28:14:14:color=white")
        if tr == "scale_in":
            # Cresce 0.88→1.0 dissolvendo (eval por frame; overlay recentra).
            grow = (f"0.88+0.12*if(lt(t,{end_e:.3f}),"
                    f"(t-{start:.3f})/{entry:.3f},1)")
            chain = (f"{base_card},rotate={rot:.4f}:fillcolor=white,"
                     f"scale=w='iw*({grow})':h='ih*({grow})':eval=frame,"
                     f"format=rgba,fade=t=in:st={start:.3f}:d={fade_d:.2f}:alpha=1")
        elif tr == "tilt_in":
            # Assenta de +8° até a rotação do cartão, dissolvendo junto.
            settle = (f"{rot:.4f}+0.14*if(lt(t,{end_e:.3f}),"
                      f"({end_e:.3f}-t)/{entry:.3f},0)")
            chain = (f"{base_card},rotate='{settle}':fillcolor=white,"
                     f"format=rgba,fade=t=in:st={start:.3f}:d={fade_d:.2f}:alpha=1")
        else:
            chain = (f"{base_card},rotate={rot:.4f}:fillcolor=white,"
                     f"format=rgba,fade=t=in:st={start:.3f}:d={fade_d:.2f}:alpha=1")
        parts.append(f"[{i}:v]{chain}[c{i}]")

    def _target(i: int) -> tuple[str, str]:
        dx = int(valid[i].get("dx", 0))
        dy = int(valid[i].get("dy", 0))
        return (f"(W-w)/2+{dx}", f"(H-h-360)/2+40+{dy}")

    prev = "[base]"
    for i, im in enumerate(valid[1:], 1):
        x0, y0 = _target(i)
        start = float(im.get("start", 0.0))
        entry = max(0.3, float(im.get("entry_dur", 0.6)))
        end_e = start + entry
        tr = im.get("transition", "fade")
        if tr == "drop_in":
            x = f"'{x0}'"
            y = (f"'if(lt(t,{start:.3f}),-h,"
                 f"if(lt(t,{end_e:.3f}),-h+({y0}+h)*(t-{start:.3f})/{entry:.3f},"
                 f"{y0}))'")
        elif tr == "slide_left":
            x = (f"'if(lt(t,{start:.3f}),-w,"
                 f"if(lt(t,{end_e:.3f}),-w+({x0}+w)*(t-{start:.3f})/{entry:.3f},"
                 f"{x0}))'")
            y = f"'{y0}'"
        elif tr == "slide_right":
            x = (f"'if(lt(t,{start:.3f}),W,"
                 f"if(lt(t,{end_e:.3f}),W-(W-({x0}))*(t-{start:.3f})/{entry:.3f},"
                 f"{x0}))'")
            y = f"'{y0}'"
        elif tr == "fade_scale":
            # Legado (timelines antigas): dissolve com deriva sutil.
            x = f"'{x0}'"
            y = (f"'if(lt(t,{end_e:.3f}),{y0}-24+24*(t-{start:.3f})/{entry:.3f},"
                 f"{y0})'")
        else:  # fade | scale_in | tilt_in: posição final + dissolve
            # (o movimento mora no cartão: escala/rotação por frame).
            x = f"'{x0}'"
            y = f"'{y0}'"
        tag = "[vout]" if i == len(valid) - 1 else f"[m{i}]"
        parts.append(f"{prev}[c{i}]overlay=x={x}:y={y}:"
                     f"enable='between(t,{start:.3f},{duration:.3f})':"
                     f"eof_action=pass{tag}")
        prev = tag

    backend, _, vargs = _video_codec_args(cfg)
    tail = ("format=nv12,hwupload" if backend == "vaapi"
            else "format=yuv420p")
    # O último overlay já sai em [vout]; só converte o formato final.
    fc = ";".join(parts) + f";[vout]{tail}[vend]"
    out_label = "[vend]"
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for im in valid:
        cmd += ["-loop", "1", "-framerate", str(fps), "-i", im["local_path"]]
    if backend == "vaapi":
        from ..ffmpeg import vaapi_device
        cmd += ["-vaapi_device", vaapi_device() or "/dev/dri/renderD128"]
    proc = ff.run(cmd + ["-filter_complex", fc, "-map", out_label,
                         "-t", str(duration), "-r", str(fps)]
                  + vargs + ["-an", out_path])
    _check(proc, "collage")
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


def build_sfx_track(events: list[dict], total_duration: float,
                    out_path: str, seed: int = 0) -> str | None:
    """Trilha de SFX discretos p/ inserções (swish/tap sintetizados, sem assets).

    Cada evento {kind, at, gain_db, duration} vira um sopro curto com fades
    de entrada/saída, posicionado via adelay e completado com silêncio até o
    total. Ganho baixo por construção (~-26 dB): complementa a entrada da
    foto sem competir com a narração. Sem eventos, retorna None.
    """
    import os as _os
    total = max(0.5, float(total_duration))
    evs = sorted(
        (e for e in events or []
         if isinstance(e, dict) and 0 <= float(e.get("at", -1)) < total),
        key=lambda e: float(e["at"]))
    if not evs:
        return None
    _os.makedirs(_os.path.dirname(out_path) or ".", exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for idx, e in enumerate(evs):
        at_ms = int(round(float(e["at"]) * 1000))
        d = max(0.3, min(0.6, float(e.get("duration", 0.35))))
        gain = float(e.get("gain_db", -26))
        if e.get("kind") == "tap":
            freq = 140 + (idx % 2) * 20
            src = (f"sine=frequency={freq}:duration={d:.2f}:sample_rate=48000,"
                   f"volume={gain - 4:.0f}dB,afade=t=in:st=0:d=0.02,"
                   f"afade=t=out:st=0:d={d:.2f}")
        else:  # swish: ruído rosa filtrado (papel/folha), timbre levemente variado
            fcut = 750 + (idx % 3) * 100
            src = (f"anoisesrc=color=pink:duration={d + 0.15:.2f}:"
                   f"seed={seed + idx + 1}:sample_rate=48000,"
                   f"lowpass=f={fcut},volume={gain:.0f}dB,"
                   f"afade=t=in:st=0:d=0.06,"
                   f"afade=t=out:st={d - 0.25:.2f}:d=0.25")
        cmd += ["-f", "lavfi", "-i", src + f",adelay={at_ms}|{at_ms}"]
    if len(evs) == 1:
        fc = f"[0:a]apad=whole_dur={total:.2f}[aout]"
    else:
        ins = "".join(f"[{i}:a]" for i in range(len(evs)))
        fc = (f"{ins}amix=inputs={len(evs)}:normalize=0,"
              f"apad=whole_dur={total:.2f}[aout]")
    proc = ff.run(cmd + ["-filter_complex", fc, "-map", "[aout]",
                         "-t", f"{total:.2f}", "-ar", "48000", "-ac", "2",
                         out_path])
    _check(proc, "sfx")
    return out_path


def mix_sfx(narration_wav: str, sfx_wav: str, out_path: str,
            total: float) -> str:
    """Soma o SFX à narração sem tocar no volume dela (amix sem normalizar)."""
    total = max(0.5, float(total))
    fc = ("[0:a]aresample=48000,aformat=channel_layouts=stereo[nr];"
          "[1:a]aresample=48000,aformat=channel_layouts=stereo[sx];"
          "[nr][sx]amix=inputs=2:normalize=0[m];"
          f"[m]apad=whole_dur={total:.2f}[aout]")
    proc = ff.run(["ffmpeg", "-y", "-v", "error", "-i", narration_wav,
                   "-i", sfx_wav, "-filter_complex", fc, "-map", "[aout]",
                   "-t", f"{total:.2f}", "-ar", "48000", "-ac", "2", out_path])
    _check(proc, "mix-sfx")
    return out_path


def _escape_drawtext(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\\'").replace("%", "\\%").replace(",", "\\,"))


def _wrap_title_lines(title: str, width: int = 24,
                      max_lines: int = 3) -> list[str]:
    """Quebra o título em poucas linhas curtas, preservando o '?' final."""
    words, lines, cur = title.strip().split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if len(trial) > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    lines = [ln for ln in lines if ln][:max_lines]
    if len(lines) == max_lines and len(title.strip()) > sum(
            len(ln) for ln in lines) + max_lines:
        lines[-1] = lines[-1][: width - 3].rstrip() + "…?"
    return lines


def burn_final(silent_path: str, subs_ass: str | None, wav_path: str | None,
               out_path: str, cfg: CurioConfig, total: float,
               title: str | None = None,
               title_fontfile: str | None = None) -> dict:
    """silent + legendas queimadas + áudio → MP4 final (um encode só).

    Com `title`, queima a pergunta de abertura nos primeiros 5 s (caixa
    preta própria, topo fora da zona das legendas). Sem título, idêntico
    ao comportamento anterior.
    """
    ff.require_tools()
    backend, encoder, vargs = _video_codec_args(cfg)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", silent_path]
    vf = []
    if subs_ass:
        vf.append(f"subtitles={ff.escape_sub_path(subs_ass)}")
    if title and title.strip():
        fontfile = title_fontfile or ff.find_font_bold()
        if fontfile:
            y0 = round(cfg.height * 0.12)
            for i, line in enumerate(_wrap_title_lines(title)):
                vf.append(
                    f"drawtext=fontfile='{fontfile}':"
                    f"text='{_escape_drawtext(line)}':"
                    f"fontsize=64:fontcolor=white:"
                    f"box=1:boxcolor=black@0.85:boxborderw=28:"
                    f"x=(w-text_w)/2:y={y0 + i * 84}:"
                    f"enable='between(t,0,5)'")
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
