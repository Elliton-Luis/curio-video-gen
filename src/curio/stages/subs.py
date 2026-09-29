"""Legendas sincronizadas a partir da narração (PRD §9).

O TTS do MVP não fornece timestamps por palavra, então os tempos são
distribuídos proporcionalmente ao tamanho de cada bloco — sincronização
"suficientemente precisa" sem retranscrever o áudio.

Saída dupla a partir dos mesmos cues (mesma sincronia):
- `.srt`: artefato legível/portátil;
- `.ass`: o que o FFmpeg realmente queima no vídeo, com PlayRes, fonte,
  posição e margens explícitos (o filtro `subtitles` sem PlayRes usa
  384x288 e estoura o tamanho/posição — bug encontrado em teste visual).

Apresentação (só visual, nunca sincronia): fonte pesada e larga
(Archivo Black, OFL) branca sobre caixa preta sólida com padding
(BorderStyle 3 + Outline como respiro). Cantos arredondados NÃO existem
no ASS/libass — caixa quadrada por limitação do formato.
"""

from __future__ import annotations

import re

ARCHIVO_FAMILY = "Archivo Black"
ARCHIVO_FILE = "ArchivoBlack-Regular.ttf"
ARCHIVO_URL = ("https://github.com/google/fonts/raw/main/"
               "ofl/archivoblack/ArchivoBlack-Regular.ttf")
SUBTITLE_OUTLINE = 10  # em BorderStyle 3, vira padding da caixa preta
SUBTITLE_MARGIN_LR = 80


def _fc_match(family: str) -> tuple[str, str] | None:
    """Resolve (família, caminho) via fontconfig. None se ausente/falha."""
    import subprocess
    try:
        proc = subprocess.run(
            ["fc-match", family, "--format=%{family}|%{file}\n"],
            capture_output=True, text=True, timeout=15, check=False)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or "|" not in proc.stdout:
        return None
    found_family, _, path = proc.stdout.strip().partition("|")
    if family.lower() not in found_family.lower():
        return None
    return found_family, path


def ensure_display_font(cache_dir: str = "cache"
                        ) -> tuple[str, int, str | None]:
    """Fonte pesada p/ legendas e título: (família ASS, bold, fontfile).

    Tenta Archivo Black (OFL): já instalado → baixa p/ cache/fonts →
    instala em ~/.local/share/fonts (+fc-cache). Qualquer falha cai para
    DejaVu Sans com Bold=1 — nunca quebra o pipeline por causa de fonte.
    """
    hit = _fc_match(ARCHIVO_FAMILY)
    if hit:
        return ARCHIVO_FAMILY, 0, hit[1]
    import os
    import shutil
    import subprocess
    import urllib.request
    user_dir = os.path.expanduser("~/.local/share/fonts")
    cached = os.path.join(cache_dir, "fonts", ARCHIVO_FILE)
    installed = os.path.join(user_dir, ARCHIVO_FILE)
    try:
        if not os.path.isfile(cached):
            os.makedirs(os.path.dirname(cached), exist_ok=True)
            with urllib.request.urlopen(ARCHIVO_URL, timeout=60) as resp:
                data = resp.read(5 * 1024 * 1024 + 1)
            if len(data) < 10_000 or len(data) > 5 * 1024 * 1024:
                raise ValueError("download da fonte com tamanho suspeito")
            with open(cached, "wb") as fh:
                fh.write(data)
        if not os.path.isfile(installed):
            os.makedirs(user_dir, exist_ok=True)
            shutil.copyfile(cached, installed)
            subprocess.run(["fc-cache", "-f", user_dir],
                           capture_output=True, timeout=60, check=False)
        hit = _fc_match(ARCHIVO_FAMILY)
        if hit:
            return ARCHIVO_FAMILY, 0, hit[1]
    except Exception:  # noqa: BLE001 — fonte é apresentação, nunca fatal
        pass
    from .. import ffmpeg as ff
    return "DejaVu Sans", 1, ff.find_font_bold()


def _words(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def _sentences(text: str) -> list[str]:
    """Quebra em frases para respeitar pausas naturais da narração."""
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [p for p in parts if p]


def chunk_words(words: list[str], max_words: int = 5, max_chars: int = 36) -> list[str]:
    """Blocos curtos (≤2 linhas na tela): poucas palavras, limite de chars."""
    chunks, cur, cur_len = [], [], 0
    for word in words:
        extra = len(word) + (1 if cur else 0)
        if cur and (len(cur) >= max_words or cur_len + extra > max_chars):
            chunks.append(" ".join(cur))
            cur, cur_len = [], 0
        cur.append(word)
        cur_len += len(word) + 1
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def _fmt_ts(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_cues(text: str, total_duration: float,
               lead: float = 0.15) -> list[tuple[float, float, str]]:
    """Divide em cues curtos com tempos proporcionais. Coração da sincronia."""
    words = _words(text)
    if not words:
        raise ValueError("roteiro vazio — nada para legendar")
    # Frases primeiro (quebras naturais), depois limite de palavras/chars.
    chunks = [c for s in _sentences(text) for c in chunk_words(s.split())]
    if not chunks:
        chunks = chunk_words(words)
    weights = [sum(len(w) + 1 for w in c.split()) for c in chunks]
    total_w = sum(weights)
    usable = max(0.5, total_duration - lead)
    cues, cursor = [], lead
    for i, (cue, w) in enumerate(zip(chunks, weights)):
        share = usable * w / total_w
        start = cursor
        end = total_duration if i == len(chunks) - 1 else cursor + share
        if end - start < 1.0 and i != len(chunks) - 1:
            end = min(total_duration, start + 1.0)
        cues.append((start, end, cue))
        cursor = end
    return cues


def cues_to_srt(cues: list[tuple[float, float, str]]) -> str:
    lines = []
    for i, (start, end, cue) in enumerate(cues, 1):
        lines.append(f"{i}\n{_fmt_ts(start)} --> {_fmt_ts(end)}\n{cue}\n")
    return "\n".join(lines) + "\n"


def _ends_sentence(text: str) -> bool:
    return text.rstrip().endswith((".", "!", "?", "…", "..."))


def cues_from_words(words: list[dict], max_words: int = 5,
                    max_chars: int = 36, max_dur: float = 4.5,
                    min_dur: float = 0.8) -> list[tuple[float, float, str]]:
    """Agrupa WordBoundary reais em blocos legíveis.

    Quebra em fim de frase quando o bloco já tem corpo (≥3 palavras ou
    ≥20 chars); limites duros de palavras/chars/duração evitam estouro.
    Sem offset artificial: o primeiro bloco começa no primeiro boundary real.
    """
    clean = [w for w in words if str(w.get("text", "")).strip()]
    if not clean:
        raise ValueError("sem timestamps de palavras — nada para legendar")
    cues, cur = [], []
    for w in clean:
        cur.append(w)
        nwords = len(cur)
        nchars = sum(len(str(x["text"])) + 1 for x in cur)
        dur = float(cur[-1]["end"]) - float(cur[0]["start"])
        boundary = _ends_sentence(str(w["text"])) and (nwords >= 3 or nchars >= 20)
        hard = nwords >= max_words or nchars > max_chars or dur >= max_dur
        if boundary or hard:
            start = float(cur[0]["start"])
            end = max(float(cur[-1]["end"]), start + min_dur)
            cues.append((start, end, " ".join(str(x["text"]) for x in cur)))
            cur = []
    if cur:
        start = float(cur[0]["start"])
        end = max(float(cur[-1]["end"]), start + min_dur)
        cues.append((start, end, " ".join(str(x["text"]) for x in cur)))
    return cues


def build_srt(text: str, total_duration: float, lead: float = 0.15) -> str:
    return cues_to_srt(build_cues(text, total_duration, lead))


def _fmt_ass_ts(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def cues_to_ass(cues: list[tuple[float, float, str]], width: int, height: int,
                font_size: int, margin_v: int, alignment: int = 2,
                border_style: int = 3,
                back_colour: str = "&H00000000",
                fontname: str = "DejaVu Sans", bold: int = 0,
                outline: int = SUBTITLE_OUTLINE,
                margin_lr: int = SUBTITLE_MARGIN_LR) -> str:
    """ASS com PlayRes = resolução real: fonte/margem em pixels de verdade.

    Caixa preta sólida com padding (BorderStyle 3 + Outline como respiro,
    cores opacas): legível sobre qualquer fundo. Só apresentação — tempos,
    quebras e agrupamento dos cues intocados.
    """
    head = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{fontname},{font_size},&H00FFFFFF,&H000019FF,"
        f"&H00000000,{back_colour},{bold},0,0,0,100,100,0,0,{border_style},"
        f"{outline},0,"
        f"{alignment},{margin_lr},{margin_lr},{margin_v},1\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    body = []
    for start, end, cue in cues:
        safe = cue.replace("{", "").replace("}", "").replace("\n", " ")
        body.append(f"Dialogue: 0,{_fmt_ass_ts(start)},{_fmt_ass_ts(end)},"
                    f"Default,,0,0,0,,{safe}")
    return head + "\n".join(body) + "\n"


def write_srt(text: str, total_duration: float, srt_path: str) -> tuple[str, int]:
    srt = build_srt(text, total_duration)
    with open(srt_path, "w", encoding="utf-8") as fh:
        fh.write(srt)
    return srt_path, srt.count("-->")


def write_subtitles(text: str, total_duration: float, srt_path: str,
                    ass_path: str, width: int, height: int,
                    base_font_size: int, margin_v: int,
                    words: list[dict] | None = None,
                    fontname: str | None = None, bold: int | None = None,
                    cache_dir: str = "cache") -> int:
    """Gera SRT + ASS. Com `words` (timestamps reais), sem offset artificial;
    sem eles, cai no modo proporcional legado.

    A fonte do ASS é escalada pela altura (base calibrada para 1920),
    em pixels reais — PlayRes do ASS = resolução do vídeo. Fonte pesada
    resolvida uma vez (Archivo Black instalado sob demanda, senão DejaVu
    Bold). Sincronia e agrupamento: intocados.
    """
    if fontname is None or bold is None:
        resolved, resolved_bold, _path = ensure_display_font(cache_dir)
        fontname = resolved if fontname is None else fontname
        bold = resolved_bold if bold is None else bold
    font_size = max(20, round(base_font_size * height / 1920))
    cues = cues_from_words(words) if words else build_cues(text, total_duration)
    with open(srt_path, "w", encoding="utf-8") as fh:
        fh.write(cues_to_srt(cues))
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(cues_to_ass(cues, width, height, font_size, margin_v,
                             fontname=fontname, bold=bold))
    return len(cues)
