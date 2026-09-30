"""Interpretação do roteiro em cenas (§3).

Divide o roteiro em segmentos semânticos com texto narrado, duração estimada,
consultas visuais (em inglês — bancos de mídia respondem melhor) e intenção
visual. Via OpenRouter:Gemini 2.5 Flash (JSON) quando há chave; senão divisão
local por frases. A junção das narrações deve reproduzir o roteiro — validado,
nunca assumido.

Formato de saída rígido:
{
  "scenes": [
    {
      "index": 1,
      "narration": "texto falado correspondente",
      "visual_search_terms": "glass water"
    }
  ]
}
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
    """~1 cena a cada 9 s: 30 s→3, 45 s→5, 60 s→7 (limites 3–7).

    Meta 0 (Automático) cai no piso: quem manda no nº de cenas é o
    tamanho do roteiro (ver `scenes_for_length`).
    """
    return max(3, min(7, round(duration_target / 9)))


def scenes_for_length(words: int) -> int:
    """Nº de cenas pelo TAMANHO do roteiro (~1 cena/9 s a 150 WPM, 3–12).

    Usado no modo Automático e como piso no `visual.scenes_for_script`:
    roteiro longo = mais cenas, nunca corte para caber em meta.
    """
    est_seconds = max(1, words) / WORDS_PER_MINUTE * 60
    return max(3, min(12, round(est_seconds / 9)))


SCENES_SYSTEM_PROMPT = (
    "You split educational video scripts into visual scenes. "
    "Respond ONLY with valid JSON, no markdown, no explanations, in this exact format: "
    '{"scenes": [{"index": 1, "narration": "...", "visual_search_terms": "water glass"}]}. '
    "Rules: "
    "1) Use ONLY literal sentences from the script, in the same order, no rewriting "
    "or summarizing — the joined narrations must reproduce the script exactly; "
    "2) Each scene is a semantic moment (not arbitrary cuts); "
    "3) narration in Brazilian Portuguese; "
    "4) visual_search_terms: EXACTLY 2 English words (two simple nouns or "
    "one visual adjective + one noun) — concrete, searchable in photo banks "
    "(objects, places, eras — NEVER abstract concepts); "
    "5) Examples of ACCEPTABLE terms: \"water glass\", \"snake skin\", \"plant seedling\", "
    "\"soap bubbles\", \"roman helmet\", \"ocean wave\", \"coffee bean\", \"microscope slide\"; "
    "6) Examples of FORBIDDEN terms: \"how soap works\", \"chemical molecules reacting\", "
    "\"cinematic close-up 4k\", \"beautiful landscape\", \"scientific explanation\"; "
    "7) Split into {n} scenes (between {lo} and {hi}). "
    "IMPORTANT: visual_search_terms must be exactly 2 English words, concrete nouns/adjectives. "
    "No Portuguese, no verbs, no abstract concepts, no descriptive phrases."
)

SCENES_SYSTEM_PROMPT_EN = (
    "You split educational video scripts into visual scenes. "
    "Respond ONLY with valid JSON, no markdown, no explanations, in this exact format: "
    '{"scenes": [{"index": 1, "narration": "...", "visual_search_terms": "water glass"}]}. '
    "Rules: "
    "1) Use ONLY literal sentences from the script, in the same order, no rewriting "
    "or summarizing — the joined narrations must reproduce the script exactly; "
    "2) Each scene is a semantic moment (not arbitrary cuts); "
    "3) narration in American English; "
    "4) visual_search_terms: EXACTLY 2 English words (two simple nouns or "
    "one visual adjective + one noun) — concrete, searchable in photo banks "
    "(objects, places, eras — NEVER abstract concepts); "
    "5) Examples of ACCEPTABLE terms: \"water glass\", \"snake skin\", \"plant seedling\", "
    "\"soap bubbles\", \"roman helmet\", \"ocean wave\", \"coffee bean\", \"microscope slide\"; "
    "6) Examples of FORBIDDEN terms: \"how soap works\", \"chemical molecules reacting\", "
    "\"cinematic close-up 4k\", \"beautiful landscape\", \"scientific explanation\"; "
    "7) Split into {n} scenes (between {lo} and {hi}). "
    "IMPORTANT: visual_search_terms must be exactly 2 English words, concrete nouns/adjectives. "
    "No verbs, no abstract concepts, no descriptive phrases."
)


@dataclass
class Chapter:
    id: int
    narration: str
    duration_estimate: float
    visual_queries: list[str] = field(default_factory=list)
    global_visual_queries: list[str] = field(default_factory=list)
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
            global_visual_queries=[str(q) for q in d.get("global_visual_queries", [])],
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
    """Divisão local por frases agrupadas (sem chave OpenRouter)."""
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
    """Retorna (capítulos, fonte). Fonte: 'openrouter:gemini-2.5-flash' | 'local'."""
    n_scenes = n_scenes or scenes_for_duration(cfg.duration_target)
    lo, hi = max(3, n_scenes - 1), n_scenes + 1
    if nvidia_stage.any_llm_available():
        english = str(cfg.language or "").lower().startswith("en")
        system_prompt = (SCENES_SYSTEM_PROMPT_EN if english
                         else SCENES_SYSTEM_PROMPT)
        user_prompt = (f"Split this script into scenes:\n\n{script}"
                       if english else
                       f"Divida este roteiro em cenas:\n\n{script}")
        data, label = nvidia_stage.complete_json(
            system_prompt.format(n=n_scenes, lo=lo, hi=hi),
            user_prompt,
            cfg.nvidia_model, cfg.nvidia_base_url, cfg.nvidia_timeout,
            metrics,
            or_model=cfg.openrouter_model, or_base_url=cfg.openrouter_base_url,
            extra=cfg.llm_overrides())
        provider = label.split(":")[0]
        chapters = []
        for i, raw in enumerate(data.get("scenes", []), 1):
            narration = str(raw.get("narration", "")).strip()
            if not narration:
                continue
            # visual_search_terms vem como "term1 term2" - divide em lista
            terms_str = str(raw.get("visual_search_terms", "")).strip()
            visual_queries = terms_str.split()[:2] if terms_str else []
            chapters.append(Chapter(
                id=i,
                narration=narration,
                duration_estimate=estimate_duration(narration),
                visual_queries=visual_queries,
                global_visual_queries=visual_queries,  # mesmo para global
                visual_intent=terms_str,
            ))
        if chapters and _norm(" ".join(c.narration for c in chapters)) == _norm(script):
            return chapters, provider
        print(f"AVISO: cenas {provider} não reproduzem o roteiro literal — "
              "usando divisão local.", file=sys.stderr)
    else:
        print("Sem chave OpenRouter: cenas por divisão local.", file=sys.stderr)
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