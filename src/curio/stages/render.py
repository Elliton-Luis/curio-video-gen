"""Montagem de vídeo via FFmpeg (PRD §10, §11).

Primitivas: segmentos por cena (imagem com Ken Burns, vídeo com crop 9:16,
fallback em gradiente), concat, queima de legendas + áudio. Encoder:
Intel Arc (VA-API/AV1 no nó Intel) > QSV > libx264 (auto-detect).
"""

from __future__ import annotations

import os
import sys

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


def _hw_device() -> str:
    """Nó DRI a usar no encode por hardware (Intel primeiro, nunca sorte)."""
    from ..ffmpeg import intel_render_node, vaapi_device
    return intel_render_node() or vaapi_device() or "/dev/dri/renderD128"


def _is_vaapi(encoder: str) -> bool:
    return encoder.endswith("_vaapi")


def _video_codec_args(cfg: CurioConfig) -> tuple[str, str, list[str]]:
    backend, encoder = ff.pick_encoder(cfg.render_backend)
    if encoder == "av1_vaapi":
        # Arc B580 via VA-API: único encode HW funcional aqui (1080x1920 OK).
        return backend, encoder, ["-c:v", "av1_vaapi", "-qp", "60"]
    if encoder == "hevc_vaapi":
        return backend, encoder, ["-c:v", "hevc_vaapi", "-qp", "24"]
    if encoder == "h264_vaapi":
        return backend, encoder, ["-c:v", "h264_vaapi", "-qp", "22"]
    if encoder == "h264_qsv":
        return backend, encoder, ["-c:v", "h264_qsv", "-global_quality", "23"]
    return backend, encoder, ["-c:v", "libx264", "-preset", "veryfast",
                              "-crf", "20", "-pix_fmt", "yuv420p"]


def _hw_upload(vf: list[str], cmd: list[str], cfg: CurioConfig,
               backend: str, encoder: str = "") -> None:
    """VA-API exige frames em hardware: upload no fim da cadeia de filtros."""
    if backend == "vaapi" or _is_vaapi(encoder):
        vf.extend(["format=nv12", "hwupload"])
        cmd += ["-vaapi_device", _hw_device()]


def _check(proc, what: str) -> None:
    if proc.returncode != 0:
        raise RenderError(
            f"ffmpeg ({what}) falhou: {(proc.stderr or proc.stdout).strip()[-2000:]}"
        )


def render_image_segment(img_path: str, duration: float, out_path: str,
                         cfg: CurioConfig, variant: int = 0) -> str:
    """Foto com crop/pan/zoom que muda foco a cada visual beat."""
    w, h, fps = cfg.width, cfg.height, cfg.fps
    frames = max(1, round(duration * fps))
    base = (f"scale=2160:3840:force_original_aspect_ratio=increase:"
            f"out_range=mpeg,crop=2160:3840")
    zb = _beat_zoompan(fps, frames, variant)
    vf = (f"{base},{zb}:d={frames}:s={w}x{h}:fps={fps},format=yuv420p")
    backend, encoder, vargs = _video_codec_args(cfg)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-loop", "1", "-framerate", str(fps), "-i", img_path]
    vf_list = [vf]
    _hw_upload(vf_list, cmd, cfg, backend, encoder)
    proc = ff.run(cmd + ["-vf", ",".join(vf_list), "-frames:v", str(frames),
                         "-r", str(fps)] + vargs + ["-an", out_path])
    _check(proc, "ken-burns")
    return out_path


def _beat_zoompan(fps: int, frames: int, variant: int = 0) -> str:
    """Deriva lenta unidirecional por segmento, sem oscilação.

    A oscilação senoidal por beat (~2,1 s) lia como tremor. Agora cada
    segmento faz UM movimento suave até o fim: zoom-in de 5% ou pan
    lateral a zoom fixo, alternando por `variant`. Amplitude pequena de
    propósito: presença sem enjoo.
    """
    total = max(1, int(frames))
    if variant % 2 == 0:
        z = f"1+0.05*on/{total}"
        x = "(iw-iw/zoom)/2"
        y = "(ih-ih/zoom)/2"
    else:
        z = "1.06"
        if (variant // 2) % 2 == 0:
            x = f"(iw-iw/zoom)*on/{total}"
        else:
            x = f"(iw-iw/zoom)*(1-on/{total})"
        y = "(ih-ih/zoom)/2"
    return (f"zoompan=z='{z}':x='{x}':y='{y}'")


def _drop_in_y(start: float, entry: float, y0: str) -> str:
    """Y da foto que CAI do álbum: queda desacelerada + assentamento.

    Três tempos, para não parecer animação de PowerPoint:
    1) antes de `start`: fora do quadro (y = -h), invisível;
    2) durante `entry`: cai da altura com desaceleração (ease-out
       cúbico) — a foto chega "pesada", não deslizando em linha reta;
    3) depois: micro-quique amortecido (2 travas de ~6 px que somem),
       como papel que pousa e assenta sobre as outras fotos.

    Tudo dentro de `entry` (~0.6 s): é complemento da narração, não um
    efeito para chamar atenção. As expressões vêm entre aspas simples
    porque o parser do ffmpeg usa a vírgula como separador de filtro.
    """
    end_e = start + entry
    settle = 0.18  # duração do assentamento
    p = f"clip((t-{start:.3f})/{entry:.3f},0,1)"
    ease = f"(1-pow(1-{p},3))"
    fall = f"(-h+({y0}+h)*{ease})"
    q = f"clip((t-{end_e:.3f})/{settle:.3f},0,1)"
    bounce = f"(({y0})+6*sin(PI*{q})*(1-{q}))"
    return (f"'if(lt(t,{start:.3f}),-h,"
            f"if(lt(t,{end_e:.3f}),{fall},{bounce}))'")


def render_collage_segment(images: list[dict], duration: float,
                            out_path: str, cfg: CurioConfig,
                            variant: int = 0,
                            backgrounds: list[dict] | None = None) -> str:
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
    backgrounds = [im for im in (backgrounds or [])
                   if im.get("local_path") and _os.path.isfile(im["local_path"])]
    if not valid and backgrounds:
        valid = [backgrounds[0]]
    if not valid:
        return render_fallback_segment(
            duration, out_path, cfg, _wrap_title("curio"))
    if len(valid) == 1 and len(backgrounds) <= 1:
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

    base_scale = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase:"
                  f"out_range=mpeg,crop={w * 2}:{h * 2}")
    sources = backgrounds or [valid[0]]
    parts = []
    remaining = frames
    weight = sum(float(im.get("duration", duration)) for im in sources)
    for index, source in enumerate(sources):
        count = (remaining if index == len(sources) - 1 else
                 max(1, min(remaining - len(sources) + index + 1,
                            round(frames * float(source.get("duration", duration)) / weight))))
        remaining -= count
        if source.get("kind") == "video":
            motion = f"scale={w}:{h},fps={fps}"
        else:
            motion = f"{_beat_zoompan(fps, count, variant + index)}:d={count}:s={w}x{h}:fps={fps}"
        parts.append(f"[{index}:v]{base_scale},{motion},trim=end_frame={count},"
                     f"setpts=PTS-STARTPTS,format=yuv420p,setsar=1[bg{index}]")
    parts.append("".join(f"[bg{i}]" for i in range(len(sources))) +
                 f"concat=n={len(sources)}:v=1:a=0[base]")
    for i, im in enumerate(valid[1:], 1):
        rot = float(im.get("rotation_deg", 0.0)) * math.pi / 180
        start = float(im.get("start", 0.0))
        entry = max(0.3, float(im.get("entry_dur", 0.6)))
        end_e = start + entry
        fade_d = min(0.4, max(0.2, entry * 0.5))
        tr = im.get("transition", "fade")
        # Sem moldura branca: a foto é recortada e pousa direto sobre o
        # fundo. A moldura de 14px + fillcolor=white deixava um retângulo
        # claro recortado no meio da imagem — lia como defeito de render,
        # não como foto de álbum. `format=rgba` antes da rotação e
        # `fillcolor=none` depois: os cantos da inclinação ficam
        # transparentes, como papel de verdade.
        base_card = (f"scale={card_w}:1000:force_original_aspect_ratio=decrease,"
                     f"format=rgba")
        if tr == "scale_in":
            # Cresce 0.88→1.0 dissolvendo (eval por frame; overlay recentra).
            grow = (f"0.88+0.12*if(lt(t,{end_e:.3f}),"
                    f"(t-{start:.3f})/{entry:.3f},1)")
            chain = (f"{base_card},rotate={rot:.4f}:fillcolor=none,"
                     f"scale=w='iw*({grow})':h='ih*({grow})':eval=frame,"
                     f"fade=t=in:st={start:.3f}:d={fade_d:.2f}:alpha=1")
        elif tr == "tilt_in":
            # Assenta de +8° até a rotação do cartão, dissolvendo junto.
            settle = (f"{rot:.4f}+0.14*if(lt(t,{end_e:.3f}),"
                      f"({end_e:.3f}-t)/{entry:.3f},0)")
            chain = (f"{base_card},rotate='{settle}':fillcolor=none,"
                     f"fade=t=in:st={start:.3f}:d={fade_d:.2f}:alpha=1")
        else:
            chain = (f"{base_card},rotate={rot:.4f}:fillcolor=none,"
                     f"fade=t=in:st={start:.3f}:d={fade_d:.2f}:alpha=1")
        parts.append(f"[{len(sources) + i - 1}:v]{chain}[c{i}]")

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
            y = _drop_in_y(start, entry, y0)
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

    backend, encoder, vargs = _video_codec_args(cfg)
    tail = ("format=nv12,hwupload" if _is_vaapi(encoder)
            else "format=yuv420p")
    # O último overlay já sai em [vout]; só converte o formato final.
    fc = ";".join(parts) + f";{prev}{tail}[vend]"
    out_label = "[vend]"
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for im in [*sources, *valid[1:]]:
        cmd += (["-stream_loop", "-1"] if im.get("kind") == "video" else
                ["-loop", "1", "-framerate", str(fps)]) + ["-i", im["local_path"]]
    if _is_vaapi(encoder):
        cmd += ["-vaapi_device", _hw_device()]
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
    backend, encoder, vargs = _video_codec_args(cfg)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", str(round(ss, 2)), "-i", vid_path]
    vf_list = [vf]
    _hw_upload(vf_list, cmd, cfg, backend, encoder)
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
    backend, encoder, vargs = _video_codec_args(cfg)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", _background_src(cfg)]
    _hw_upload(vf, cmd, cfg, backend, encoder)
    proc = ff.run(cmd + ["-vf", ",".join(vf), "-t", str(duration),
                         "-r", str(fps)] + vargs + ["-an", out_path])
    _check(proc, "fallback")
    return out_path


def concat_copy(paths: list[str], out_path: str, cfg: CurioConfig | None = None) -> str:
    """Concatena segmentos; sem re-encode quando dá para evitá-lo.

    O "sem re-encode" era uma premissa errada. Cada segmento é gravado
    como uma SÉRIE de codec própria, e o `-c copy` do demuxer concat junta
    as séries sem fundi-las: o arquivo final tem N cabecalhos de sequência
    e o segundo encode (legendas + título + áudio) precisa reiniciar o
    filtergraph ao atravessar cada fronteira.

    O `hwupload` do VA-API não implementa reinicialização, então morre com
    -38 (ENOSYS) e imprime a lista completa de pixel formats do encoder
    tentando negociar. O sintoma é confuso: falha sempre na fronteira do
    SEGUNDO segmento — 14,9 s num vídeo de 12 cenas — muito depois de
    qualquer coisa ter dado errado, e o `final.mp4` fica truncado no
    disco como se tivesse funcionado.

    Por isso: quando o encode final é VA-API, normalizamos para uma série
    única antes. O encode é por software porque é justamente o software
    que tolera o reinit; com `libx264` os 88 s do exemplo passam, e o
    segundo passe por VA-API então funciona (medido: 13 s + 19 s para um
    vídeo de 88 s). Quando o encode final é por software, o problema não
    existe e nada é normalizado — não se paga um passe que ninguém
    precisa.
    """
    list_path = out_path + ".files.txt"
    with open(list_path, "w", encoding="utf-8") as fh:
        for p in paths:
            # Absoluto: o demuxer concat resolve relativo ao .txt, não ao CWD.
            fh.write(f"file '{os.path.abspath(p)}'\n")
    proc = ff.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                   "-i", list_path, "-c", "copy", out_path])
    _check(proc, "concat")

    if cfg is not None and _needs_single_sequence(cfg):
        _normalize_sequence(list_path, out_path)
    return out_path


XFADE_KINDS = ("fade", "fadeblack", "fadewhite", "wipeleft",
               "slideright", "smoothleft")

def concat_with_transitions(paths: list[str], out_path: str,
                            cfg: CurioConfig,
                            transitions: list[float],
                            kinds: list[str] | None = None) -> str:
    """Concatena cenas com cross-dissolve curto sem encurtar a timeline.

    A próxima entrada recebe um clone de seu primeiro frame durante o overlap;
    assim o xfade consome o intervalo de dissolve mas mantém cada limite de
    cena no timestamp original. Transições ≤0 continuam cortes secos.
    `kinds` escolhe o efeito xfade por limite; tipo desconhecido cai em fade.
    """
    if len(paths) < 2 or not any(float(x) > 0 for x in transitions):
        return concat_copy(paths, out_path, cfg)
    ff.require_tools()
    durations = [ff.probe_duration(p) for p in paths]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for path in paths:
        cmd += ["-i", path]
    filters = [f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p[in{i}]"
               for i in range(len(paths))]
    current = "in0"
    elapsed = durations[0]
    for i in range(1, len(paths)):
        requested = (float(transitions[i - 1]) if i - 1 < len(transitions)
                     else 0.0)
        d = min(max(0.0, requested), durations[i - 1] - 0.04,
                durations[i] - 0.04)
        if d <= 0:
            # O caller normalmente escolhe cut=0; uma duração impraticável
            # também degrada para corte, nunca falha o vídeo.
            # Concat filter mantém a timeline e mistura este caso com a cadeia.
            out = f"out{i}"
            filters.append(f"[{current}][in{i}]concat=n=2:v=1:a=0[{out}]")
            current = out
            elapsed += durations[i]
            continue
        padded = f"p{i}"
        filters.append(
            f"[in{i}]tpad=start_mode=clone:start_duration={d:.3f}[{padded}]")
        out = f"out{i}"
        kind = (kinds[i - 1] if kinds and i - 1 < len(kinds)
                and kinds[i - 1] in XFADE_KINDS else "fade")
        filters.append(
            f"[{current}][{padded}]xfade=transition={kind}:duration={d:.3f}:"
            f"offset={max(0.0, elapsed - d):.3f}[{out}]")
        current = out
        elapsed += durations[i]
    backend, encoder, vargs = _video_codec_args(cfg)
    upload_filters: list[str] = []
    _hw_upload(upload_filters, cmd, cfg, backend, encoder)
    if upload_filters:
        filters.append(f"[{current}]{','.join(upload_filters)}[vhw]")
        current = "vhw"
    cmd += ["-filter_complex", ";".join(filters), "-map", f"[{current}]",
            "-an", "-r", str(cfg.fps)]
    cmd += vargs + ["-t", f"{sum(durations):.3f}", out_path]
    _check(ff.run(cmd), "concat-transitions")
    return out_path


def _needs_single_sequence(cfg: CurioConfig) -> bool:
    """O encode final vai usar VA-API? (só aí o multi-série é fatal.)"""
    try:
        _backend, encoder = ff.pick_encoder(cfg.render_backend)
    except Exception:  # noqa: BLE001 — detecção falha: melhor normalizar
        return True
    return encoder.endswith("_vaapi")


def _normalize_sequence(list_path: str, out_path: str) -> None:
    """Regrava o concat como UMA série de codec, para o próximo encode."""
    tmp = out_path + ".norm.mp4"
    proc = ff.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                   "-i", list_path, "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "16", "-pix_fmt", "yuv420p", tmp])
    if proc.returncode != 0:
        # Normalização falhou: fica o concat original, e o próximo
        # encode é que decide se aguenta. Melhor um arquivo possivelmente
        # multi-série do que nenhum arquivo.
        print(f"AVISO: não foi possível normalizar a série de codecs "
              f"({(proc.stderr or '').strip()[-200:] or 'erro desconhecido'}) "
              f"— o encode por hardware pode falhar.", file=sys.stderr)
        if os.path.exists(tmp):
            os.remove(tmp)
        return
    os.replace(tmp, out_path)


# Nível dos SFX. Os geradores do ffmpeg não saem em 0 dBFS: `sine` com
# beep_factor=1 mede -11.5 dBFS de pico e o pink filtrado ~-10 dBFS. Sem
# esta calibração, "volume=-30dB" significaria -30 dB *sobre* o pico do
# gerador, ou seja, -40 dBFS — inaudível, o oposto de "discreto, mas que
# está lá". Com ela, `gain_db` passa a ser o PICO ALVO em dBFS, número
# que dá para comparar com o da narração (-24 dB abaixo da fala comum).
_SINE_PEAK_DB = -11.5
_NOISE_PEAK_DB = -10.1


def build_sfx_track(events: list[dict], total_duration: float,
                    out_path: str, seed: int = 0) -> str | None:
    """Trilha de SFX pontuais: arquivo da biblioteca ou swish/tap sintético.

    Cada evento {kind, at, gain_db, duration} vira um sopro curto com fades
    de entrada/saída, posicionado via adelay e completado com silêncio até o
    total. `gain_db` é o pico alvo em dBFS (ver _SINE_PEAK_DB): -30 é
    "presente sem competir". Sem eventos, retorna None.
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
    filters = []
    labels = []
    for idx, e in enumerate(evs):
        at_ms = int(round(float(e["at"]) * 1000))
        d = max(0.3, min(0.6, float(e.get("duration", 0.35))))
        target = float(e.get("gain_db", -30))
        path = str(e.get("path") or "")
        if path and os.path.isfile(path):
            cmd += ["-i", path]
            source = f"[{idx}:a]"
            chain = (f"{source}atrim=duration={d:.3f},asetpts=PTS-STARTPTS,"
                     f"volume={target:.1f}dB,afade=t=in:st=0:d=0.025,"
                     f"afade=t=out:st={max(0.0, d - 0.12):.3f}:"
                     f"d={min(0.12, d):.3f}")
        elif e.get("kind") == "tap":
            # Objeto pousando no álbum: pulso grave curto, com "corpo"
            # (a queda) e cauda rápida (o impacto).
            freq = 140 + (idx % 2) * 20
            gain = target - _SINE_PEAK_DB
            src = (f"sine=frequency={freq}:duration={d:.2f}:beep_factor=1:"
                   f"sample_rate=48000,volume={gain:.1f}dB,"
                   f"afade=t=in:st=0:d=0.015,"
                   f"afade=t=out:st={d * 0.35:.2f}:d={d * 0.65:.2f}")
            cmd += ["-f", "lavfi", "-i", src]
            source = f"[{idx}:a]"
        else:  # swish: ruído rosa filtrado (papel/folha), timbre levemente variado
            fcut = 750 + (idx % 3) * 100
            gain = target - _NOISE_PEAK_DB
            src = (f"anoisesrc=color=pink:duration={d + 0.15:.2f}:"
                   f"seed={seed + idx + 1}:sample_rate=48000,"
                   f"lowpass=f={fcut},volume={gain:.1f}dB,"
                   f"afade=t=in:st=0:d=0.06,"
                   f"afade=t=out:st={d - 0.25:.2f}:d=0.25")
            cmd += ["-f", "lavfi", "-i", src]
            source = f"[{idx}:a]"
        label = f"sfx{idx}"
        if path and os.path.isfile(path):
            filters.append(f"{chain},adelay={at_ms}|{at_ms}[{label}]")
        else:
            filters.append(f"{source}adelay={at_ms}|{at_ms}[{label}]")
        labels.append(f"[{label}]")
    if len(evs) == 1:
        filters.append(f"{labels[0]}apad=whole_dur={total:.2f}[aout]")
    else:
        filters.append(
            f"{''.join(labels)}amix=inputs={len(evs)}:normalize=0,"
            f"apad=whole_dur={total:.2f}[aout]")
    fc = ";".join(filters)
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
            .replace("'", r"'\''").replace("%", "\\%").replace(",", "\\,"))


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
               title_fontfile: str | None = None,
               music_path: str | None = None,
                music_gain_db: float = -5.0,
               music_ducking: bool = True,
               final_fade: float = 0.0) -> dict:
    """silent + legendas queimadas + áudio → MP4 final (um encode só).

    Com `title`, queima a pergunta de abertura nos primeiros 5 s (caixa
    preta própria, topo fora da zona das legendas). Sem título, idêntico
    ao comportamento anterior.
    """
    ff.require_tools()
    backend, encoder, vargs = _video_codec_args(cfg)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", silent_path]
    voice_idx = None
    music_idx = None
    if wav_path:
        voice_idx = 1
        cmd += ["-i", wav_path]
    if music_path and os.path.isfile(music_path):
        music_idx = 2 if voice_idx is not None else 1
        cmd += ["-stream_loop", "-1", "-i", music_path]
    vf = []
    if subs_ass:
        vf.append(f"subtitles={ff.escape_sub_path(subs_ass)}")
    if title and title.strip():
        fontfile = title_fontfile or ff.find_font_bold()
        if fontfile:
            # Título em relevo (contorno + sombra), sem caixa — mesmo
            # idioma visual das legendas.
            y0 = round(cfg.height * 0.22)
            for i, line in enumerate(_wrap_title_lines(title)):
                vf.append(
                    f"drawtext=fontfile='{fontfile}':"
                    f"text='{_escape_drawtext(line)}':"
                    f"fontsize=64:fontcolor=white:"
                    f"borderw=3:bordercolor=black:"
                    f"shadowcolor=black@0.9:shadowx=4:shadowy=4:"
                    f"x=(w-text_w)/2:y={y0 + i * 84}:"
                    f"enable='between(t,0,5)'")
    fade = max(0.0, min(2.0, float(final_fade or 0.0)))
    if fade and total > fade:
        vf.append(f"fade=t=out:st={max(0.0, total - fade):.3f}:d={fade:.3f}")
    if backend == "vaapi" or _is_vaapi(encoder):
        vf.extend(["format=nv12", "hwupload"])
        cmd += ["-vaapi_device", _hw_device()]
    audio_graph = None
    if voice_idx is not None and music_idx is not None:
        bed_filters = [
            f"[{music_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"loudnorm=I=-21:TP=-2:LRA=11,"
            f"volume={float(music_gain_db):.1f}dB,atrim=duration={total:.3f},"
            f"asetpts=PTS-STARTPTS,afade=t=in:st=0:d={min(0.8, total / 4):.3f},"
            f"afade=t=out:st={max(0.0, total - min(1.2, total / 3)):.3f}:"
            f"d={min(1.2, total / 3):.3f}[bed]",
            f"[{voice_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"apad=whole_dur={total:.3f}"
            f"{',asplit=2[voice_sc][voice]' if music_ducking else '[voice]'}",
        ]
        if music_ducking:
            bed_filters.append(
                "[bed][voice_sc]sidechaincompress=threshold=0.04:ratio=3:"
                "attack=400:release=1100[ducked]")
            bed_label = "ducked"
        else:
            bed_label = "bed"
        bed_filters.append(
            f"[voice][{bed_label}]amix=inputs=2:duration=first:normalize=0,"
            f"alimiter=limit=0.97:attack=5:release=50:latency=1,"
            f"apad=whole_dur={total:.3f}[aout]")
        audio_graph = ";".join(bed_filters)
        cmd += ["-map", "0:v", "-map", "[aout]",
                "-filter_complex", audio_graph]
    elif voice_idx is not None:
        cmd += ["-map", "0:v", "-map", f"{voice_idx}:a"]
    elif music_idx is not None:
        cmd += ["-map", "0:v", "-map", f"{music_idx}:a",
                "-af", f"aresample=48000,loudnorm=I=-21:TP=-2:LRA=11,"
                       f"volume={float(music_gain_db):.1f}dB,"
                       f"afade=t=in:st=0:d={min(0.8, total / 4):.3f},"
                       f"afade=t=out:st={max(0.0,total-min(1.2,total/3)):.3f}:"
                       f"d={min(1.2,total/3):.3f}"]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-r", str(cfg.fps), "-t", str(total)] + vargs
    if voice_idx is not None or music_idx is not None:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000"]
        if voice_idx is not None and music_idx is None:
            # Compatibilidade exata do caminho anterior: completar a cauda
            # da narração até o limite de render, sem truncar pelo stream.
            cmd += ["-af", f"aresample=48000,apad=whole_dur={total}"]
        else:
            cmd.append("-shortest")
    cmd += ["-movflags", "+faststart", out_path]
    _check(ff.run(cmd), encoder)
    actual = ff.probe_duration(out_path)
    return {"backend": backend, "encoder": encoder,
            "duration": actual, "path": out_path}
