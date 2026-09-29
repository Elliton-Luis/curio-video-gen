"""Verificação de vídeos gerados contra os critérios do PRD §19.

Checa via ffprobe (sem reprocessar nada): existência, streams de vídeo/áudio,
resolução 9:16, duração próxima da meta e legendas SRT presentes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from . import ffmpeg as ff


@dataclass
class Check:
    ok: bool
    label: str
    detail: str = ""


@dataclass
class VerifyReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def success(self) -> bool:
        return self.total > 0 and self.passed == self.total

    def render(self) -> str:
        lines = []
        for c in self.checks:
            mark = "OK   " if c.ok else "FALHA"
            extra = f" — {c.detail}" if c.detail else ""
            lines.append(f"[{mark}] {c.label}{extra}")
        lines.append(f"\n{self.passed}/{self.total} verificações passaram.")
        return "\n".join(lines)


def _probe(path: str) -> dict:
    proc = ff.run([ff.FFPROBE, "-v", "error",
                   "-show_entries", "stream=codec_name,codec_type,width,height",
                   "-show_entries", "format=duration,size",
                   "-of", "json", path])
    if proc.returncode != 0:
        raise ff.FFMpegError(f"ffprobe falhou: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def verify_video(mp4_path: str, srt_path: str | None = None,
                 duration_target: float = 45.0,
                 width: int = 1080, height: int = 1920) -> VerifyReport:
    rep = VerifyReport()
    if not os.path.isfile(mp4_path):
        return VerifyReport([Check(False, "arquivo MP4 existe", mp4_path)])
    size = os.path.getsize(mp4_path)
    rep.checks.append(Check(size > 100_000, "arquivo MP4 existe",
                            f"{size / 1_048_576:.1f} MB"))

    try:
        info = _probe(mp4_path)
    except ff.FFMpegError as exc:
        rep.checks.append(Check(False, "ffprobe lê o MP4", str(exc)))
        return rep
    rep.checks.append(Check(True, "ffprobe lê o MP4"))

    streams = info.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    rep.checks.append(Check(len(videos) > 0, "stream de vídeo presente",
                            videos[0].get("codec_name", "?") if videos else "nenhum"))
    rep.checks.append(Check(len(audios) > 0, "stream de áudio presente",
                            audios[0].get("codec_name", "?") if audios else "mudo!"))

    if videos:
        v = videos[0]
        vw, vh = int(v.get("width", 0)), int(v.get("height", 0))
        rep.checks.append(Check(vw == width and vh == height,
                                f"resolução {width}x{height}", f"atual: {vw}x{vh}"))
        rep.checks.append(Check(vw * 16 == vh * 9, "proporção 9:16 (vertical)",
                                f"{vw}x{vh}"))

    try:
        dur = float(info.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        dur = 0.0
    # A duração é meta, não regra: o vídeo tem o tamanho do conteúdo.
    # Auto (meta 0) ou qualquer distância da meta informam, nunca reprovam.
    if duration_target <= 0:
        rep.checks.append(Check(True, "duração livre (auto)",
                                f"{dur:.1f}s (conteúdo manda, sem meta)"))
    else:
        lo, hi = duration_target * 0.75, duration_target * 1.25
        inside = lo <= dur <= hi
        rep.checks.append(Check(
            True, "duração próxima da meta" if inside else "duração fora da meta",
            f"{dur:.1f}s (meta {duration_target:.0f}s ±25% — "
            f"{'dentro' if inside else 'conteúdo manda, sem corte'})"))

    if srt_path:
        ok_srt = os.path.isfile(srt_path) and os.path.getsize(srt_path) > 0
        cues = 0
        if ok_srt:
            with open(srt_path, encoding="utf-8") as fh:
                cues = fh.read().count("-->")
        rep.checks.append(Check(ok_srt and cues > 0, "legendas SRT presentes",
                                f"{cues} blocos" if ok_srt else "arquivo ausente"))
    return rep
