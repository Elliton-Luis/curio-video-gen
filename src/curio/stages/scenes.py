"""Interpretação do roteiro em cenas (§3).

Divide o roteiro em segmentos semânticos com texto narrado, duração estimada,
consultas visuais (em inglês — bancos de mídia respondem melhor) e intenção
visual. Via NVIDIA (JSON) quando há chave; senão divisão local por frases.
A junção das narrações deve reproduzir o roteiro — validado, nunca assumido.
"""

from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass, field

from ..config import CurioConfig
from . import nvidia as nvidia_stage

TARGET_SCENES = 5
WORDS_PER_MINUTE = 150


def scenes_for_duration(duration_target: float) -> int:
    """~1 cena a cada 9 s: 30 s→3, 45 s→5, 60 s→7 (limites 3–7)."""
    return max(3, min(7, round(duration_target / 9)))

SCENES_SYSTEM_PROMPT = (
    "Você divide roteiros de vídeo educativo em cenas visuais. "
    "Responda SOMENTE com JSON válido, sem markdown nem explicações, neste formato: "
    '{{"title": "...", "chapters": [{{"id": 1, "narration": "...", '
    '"visual_queries": ["english query 1", "english query 2"], '
    '"visual_intent": "short english intent"}}]}}. Regras: '
    "1) use APENAS frases literais do roteiro, na mesma ordem, sem reescrever "
    "nem resumir — a junção das narrations deve reproduzir o roteiro; "
    "2) cada chapter é um momento semântico (não corte arbitrário); "
    "3) narration em português do Brasil; visual_queries e visual_intent em "
    "inglês, concretos e buscáveis em bancos de fotos (objetos, lugares, "
    "épocas — nunca conceitos abstratos); "
    "4) divida em {n} chapters (entre {lo} e {hi})."
)


@dataclass
class Chapter:
    id: int
    narration: str
    duration_estimate: float
    visual_queries: list[str] = field(default_factory=list)
    visual_intent: str = ""
    start: float = 0.0
    end: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Chapter":
        return cls(
            id=int(d.get("id", 0)),
            narration=str(d.get("narration", "")),
            duration_estimate=float(d.get("duration_estimate", 0)),
            visual_queries=[str(q) for q in d.get("visual_queries", [])],
            visual_intent=str(d.get("visual_intent", "")),
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
        )


def estimate_duration(narration: str, wpm: int = WORDS_PER_MINUTE) -> float:
    return max(2.5, round(len(narration.split()) / wpm * 60, 2))


def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"[^\w\s]", "", text)


def _local_chapters(script: str, n_scenes: int = TARGET_SCENES) -> list[Chapter]:
    """Divisão local por frases agrupadas (sem chave NVIDIA)."""
    from . import subs as subs_stage
    sentences = subs_stage._sentences(script)
    if not sentences:
        raise ValueError("roteiro vazio — nada para dividir em cenas")
    per = max(1, round(len(sentences) / n_scenes))
    chapters = []
    for i in range(0, len(sentences), per):
        narration = " ".join(sentences[i:i + per])
        chapters.append(Chapter(
            id=len(chapters) + 1,
            narration=narration,
            duration_estimate=estimate_duration(narration),
            visual_queries=[],
            visual_intent="local fallback (sem consulta visual)",
        ))
    return chapters


def build_chapters(script: str, cfg: CurioConfig,
                   n_scenes: int | None = None, metrics=None) -> tuple[list[Chapter], str]:
    """Retorna (capítulos, fonte). Fonte: 'nvidia' | 'local'."""
    n_scenes = n_scenes or scenes_for_duration(cfg.duration_target)
    lo, hi = max(3, n_scenes - 1), n_scenes + 1
    creds = nvidia_stage.NvidiaCredentials.from_env()
    if creds.available:
        data = nvidia_stage.complete_json(
            SCENES_SYSTEM_PROMPT.format(n=n_scenes, lo=lo, hi=hi),
            f"Divida este roteiro em cenas:\n\n{script}",
            cfg.nvidia_model, cfg.nvidia_base_url, cfg.nvidia_timeout,
            metrics)
        chapters = []
        for i, raw in enumerate(data.get("chapters", []), 1):
            narration = str(raw.get("narration", "")).strip()
            if not narration:
                continue
            chapters.append(Chapter(
                id=i,
                narration=narration,
                duration_estimate=estimate_duration(narration),
                visual_queries=[str(q) for q in raw.get("visual_queries", [])][:3],
                visual_intent=str(raw.get("visual_intent", "")),
            ))
        if chapters and _norm(" ".join(c.narration for c in chapters)) == _norm(script):
            return chapters, "nvidia"
        print("AVISO: cenas NVIDIA não reproduzem o roteiro literal — "
              "usando divisão local.", file=sys.stderr)
    else:
        print("Sem chave NVIDIA: cenas por divisão local.", file=sys.stderr)
    return _local_chapters(script, n_scenes), "local"


def apply_timings(chapters: list[Chapter],
                  words: list[dict]) -> list[Chapter]:
    """Alinha capítulos aos WordBoundary reais por índice de palavra."""
    script_norm = [_norm(w) for w in " ".join(c.narration for c in chapters).split()]
    wb_norm = [_norm(str(w.get("text", ""))) for w in words]
    wb_norm = [w for w in wb_norm if w]
    if len(script_norm) != len(wb_norm):
        raise ValueError(
            f"contagem de palavras diverge (roteiro={len(script_norm)}, "
            f"áudio={len(wb_norm)})")
    idx, out = 0, []
    for ch in chapters:
        n = len(ch.narration.split())
        span = words[idx:idx + n]
        out.append(Chapter(
            id=ch.id, narration=ch.narration,
            duration_estimate=ch.duration_estimate,
            visual_queries=ch.visual_queries, visual_intent=ch.visual_intent,
            start=float(span[0]["start"]), end=float(span[-1]["end"])))
        idx += n
    return out
