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


def scenes_for_duration(duration_target: float,
                        target_seconds: float = 9.0) -> int:
    """~1 cena a cada `target_seconds`: 30 s→3, 45 s→5, 60 s→7 (3–7).

    Meta 0 (Automático) cai no piso: quem manda no nº de cenas é o
    tamanho do roteiro (ver `scenes_for_length`).
    """
    alvo = max(4.0, float(target_seconds or 9.0))
    return max(3, min(9, round(duration_target / alvo)))


def scenes_for_length(words: int, target_seconds: float = 9.0) -> int:
    """Nº de cenas pelo TAMANHO do roteiro e o ALVO de segundos por cena.

    Usado no modo Automático e como piso no `visual.scenes_for_script`:
    roteiro longo = mais cenas, nunca corte para caber em meta.

    `target_seconds` é o lever de pacing do gênero. É aqui que "cenas
    curtas e transformações frequentes" (etimologia, 7,5 s) e "tempo
    suficiente para o diagra ser compreendido" (ciência, 14 s) viram
    números de cena diferentes — e não adjetivos no prompt. Um perfil que
    não mexesse aqui seria exatamente o "rótulo que muda o texto".
    """
    est_seconds = max(1, words) / WORDS_PER_MINUTE * 60
    alvo = max(4.0, float(target_seconds or 9.0))
    return max(3, min(14, round(est_seconds / alvo)))


SCENES_SYSTEM_PROMPT = (
    "You split educational video scripts into visual scenes. "
    "Respond ONLY with valid JSON, no markdown, no explanations, in this exact format: "
    '{{"scenes": [{{"index": 1, "narration": "...", "subject": "...", '
    '"visual_type": "literal", "visual_search_terms": ["..."], '
    '"visual_entities": ["..."], "context": ["..."], "forbidden": ["..."]}}]}}. '
    "Rules: "
    "1) Use ONLY literal sentences from the script, in the same order, no rewriting "
    "or summarizing — the joined narrations must reproduce the script exactly; "
    "2) Each scene is a semantic moment (not arbitrary cuts); "
    "3) narration in Brazilian Portuguese; "
    "4) visual_search_terms: 3 to 5 English terms, 1 to 4 words each, concrete "
    "nouns or one visual adjective + one noun, searchable in photo banks. "
    "ALWAYS include the topic context in EVERY term so an ambiguous word cannot "
    "drift: write \"thermal paper receipt\", never \"thermal\"; write "
    "\"ink bottle\", never \"ink\". Order from most specific to most general. "
    "Acceptable: \"thermal receipt\", \"receipt paper roll\", "
    "\"thermal printer receipt\", \"faded receipt\". "
    "FORBIDDEN: bare ambiguous words, verbs, abstract concepts, "
    "\"how it works\", \"cinematic 4k\", \"beautiful landscape\"; "
    "5) visual_type - how this scene should be SHOWN, pick exactly one: "
    "\"literal\" (a real thing you can photograph: object, place, animal, person); "
    "\"mechanism\" (the scene explains HOW something works, a transformation, a "
    "cause and effect, a process - a photo cannot show it, it needs a diagram); "
    "\"historical_art\" (saints, ancient events, religion, mythology, painting, "
    "manuscripts - it needs period artwork, never a modern photo); "
    "\"conceptual\" (too abstract to photograph: use art or a visual composition); "
    "\"typographic\" (the idea IS a word: etymology, a term, a definition, a date, "
    "a comparison - show the word, not a stock photo); "
    "6) subject: the single main thing this scene is about, 1 to 4 words, in "
    "English; "
    "7) visual_entities: 2 to 4 SHORT NOUN PHRASES (1 to 4 words each) for "
    "the things that may legitimately appear on screen, in English. They are "
    "shown to the viewer as a list, so they must read as CONTENT and not as "
    "search queries: write \"USP campus\", never \"map of Rio Grande do Sul\" or "
    "\"highlighted Serra Gaucha\"; write \"wine bottles\", never \"tourists in "
    "Serra Gaucha 4k\". Never state here a fact you are not sure of: an item "
    "on this list is displayed as part of the video, so \"traditional European "
    "costumes\" in a scene about Rio Grande do Sul is not a stylistic "
    "choice, it is a wrong sentence on screen; "
    "8) context: 0 to 3 supporting visual settings or nearby objects, in English; "
    "9) forbidden: 2 to 5 words that would be a WRONG visual for this scene - "
    "the traps of this specific topic, in English. Use it whenever a word of the "
    "topic has another common meaning. For thermal receipt paper the traps are "
    "\"power plant\", \"steam\", \"wallpaper\", \"heat wave\"; for a saint, "
    "\"modern photography\", \"statue of liberty\"; never leave it empty when the "
    "topic has an ambiguous word. "
    "10) Split into {n} scenes (between {lo} and {hi}). "
    "IMPORTANT: visual_search_terms in English only, concrete, always carrying "
    "the topic context. No verbs, no abstract concepts."
)

SCENES_SYSTEM_PROMPT_EN = (
    "You split educational video scripts into visual scenes. "
    "Respond ONLY with valid JSON, no markdown, no explanations, in this exact format: "
    '{{"scenes": [{{"index": 1, "narration": "...", "subject": "...", '
    '"visual_type": "literal", "visual_search_terms": ["..."], '
    '"visual_entities": ["..."], "context": ["..."], "forbidden": ["..."]}}]}}. '
    "Rules: "
    "1) Use ONLY literal sentences from the script, in the same order, no rewriting "
    "or summarizing — the joined narrations must reproduce the script exactly; "
    "2) Each scene is a semantic moment (not arbitrary cuts); "
    "3) narration in American English; "
    "4) visual_search_terms: 3 to 5 English terms, 1 to 4 words each, concrete "
    "nouns or one visual adjective + one noun, searchable in photo banks. "
    "ALWAYS include the topic context in EVERY term so an ambiguous word cannot "
    "drift: write \"thermal paper receipt\", never \"thermal\"; write "
    "\"ink bottle\", never \"ink\". Order from most specific to most general. "
    "Acceptable: \"thermal receipt\", \"receipt paper roll\", "
    "\"thermal printer receipt\", \"faded receipt\". "
    "FORBIDDEN: bare ambiguous words, verbs, abstract concepts, "
    "\"how it works\", \"cinematic 4k\", \"beautiful landscape\"; "
    "5) visual_type - how this scene should be SHOWN, pick exactly one: "
    "\"literal\" (a real thing you can photograph); "
    "\"mechanism\" (the scene explains HOW something works, a transformation, a "
    "cause and effect - a photo cannot show it, it needs a diagram); "
    "\"historical_art\" (saints, ancient events, religion, mythology, painting - "
    "it needs period artwork, never a modern photo); "
    "\"conceptual\" (too abstract to photograph: use art or a visual composition); "
    "\"typographic\" (the idea IS a word: etymology, a term, a definition, a date - "
    "show the word, not a stock photo); "
    "6) subject: the single main thing this scene is about, 1 to 4 words; "
    "7) visual_entities: 2 to 4 SHORT NOUN PHRASES (1 to 4 words each) for "
    "the things that may legitimately appear on screen. They are shown to the "
    "viewer as a list, so they must read as CONTENT and not as search "
    "queries: write \"USP campus\", never \"map of Rio Grande do Sul\". Never "
    "state here a fact you are not sure of: an item on this list is displayed "
    "as part of the video; "
    "8) context: 0 to 3 supporting visual settings or nearby objects; "
    "9) forbidden: 2 to 5 words that would be a WRONG visual for this scene - "
    "the traps of this specific topic. Use it whenever a word of the topic has "
    "another common meaning; never leave it empty when the topic is ambiguous. "
    "10) Split into {n} scenes (between {lo} and {hi}). "
    "IMPORTANT: visual_search_terms in English only, concrete, always carrying "
    "the topic context. No verbs, no abstract concepts."
)


VISUAL_TYPES = ("literal", "mechanism", "historical_art", "conceptual",
                "typographic")

# Sinais de que a cena explica um PROCESSO, não uma coisa. Uma foto de
# laboratório não mostra "o calor altera o corante" — mostra um frasco.
# Reconhecer isso é o que evita a foto genérica no lugar do diagrama.
_MECHANISM_HINTS_PT = (
    "como funciona", "como faz", "por que funciona", "o que acontece quando",
    "acontece quando", "passo a passo", "etapas", "processo", "transforma",
    "se transforma", "reage", "reação", "reacao", "muda de cor", "altera",
    "mistura", "combina com", "por dentro", "por baixo dos panos",
    "mecanismo", "funciona porque", "o truque",
)
_MECHANISM_HINTS_EN = (
    "how does", "how it works", "what happens", "step by step", "process",
    "reaction", "reacts", "transforms", "converts", "breaks down",
    "mechanism", "the trick", "inside",
)
# Sinais de que a cena é histórica/religiosa/mítica: pede arte, não foto.
_HISTORICAL_HINTS = (
    "século", "seculo", "d. de", "antes de cristo", "depois de cristo",
    "império", "imperio", "rei ", "rainha ", "papa", "santo", "santa",
    "igreja", "deus", "deusa", "mito", "lenda", "profeta", "igrejo",
    "antiguidade", "idade média", "idade media", "renascimento",
    "séc.", "sec.", "century", "king ", "queen ", "saint", "church",
    "temple", "myth", "legend", "prophet", "empire", "ancient", "medieval",
    # Ordens, cargos e edifícios religiosos: é o que separa "sobre um
    # santo" de "sobre um gato". Nomes próprios isolados não são sinal
    # (todo mundo tem nome), então a lista é de institutions e cargos.
    "ordem dos", "franciscan", "dominicano", "jesuít", "jesuit", "monge",
    "monastery", "mosteiro", "convento", "abade", "bispo", "cardeal",
    "catedral", "basílica", "basilica", "apóstolo", "apostolo", "evangelho",
    "bíblia", "biblia", "oratório", "santuário", "santuario", "capela",
    "nascido em", "nasceu em", "viveu em", "morreu em",
)
# Sinais de que a cena é melhor dita com palavras e não com imagem.
_TYPOGRAPHIC_HINTS = (
    "quer dizer", "significa", "significado", "vem do latim", "vem do",
    "etimologia", "etimológica", "etimologicamente", "chama-se", "chamava",
    "o termo", "a palavra", "definicao", "definição", "etimolog",
    "significa literalmente", "means", "derived from", "etymology",
    "word comes from", "literally",
)


def classify_visual_type(narration: str) -> str:
    """Tipo de visual que serve à cena, sem depender da IA.

    Ordem importa: mecanismo e histórico são específicos e vencem; o
    textual é o mais forte sinal de "isto é uma etimologia"; o resto é
    literal. É a rede de segurança para quando não há chave de LLM — sem
    ela, tudo vira "literal" e o vídeo inteiro vira banco de imagem.
    """
    text = (narration or "").lower()
    if not text.strip():
        return "literal"
    if any(h in text for h in _MECHANISM_HINTS_PT + _MECHANISM_HINTS_EN):
        return "mechanism"
    if any(h in text for h in _TYPOGRAPHIC_HINTS):
        return "typographic"
    if any(h in text for h in _HISTORICAL_HINTS):
        return "historical_art"
    return "literal"


@dataclass
class Chapter:
    id: int
    narration: str
    duration_estimate: float
    visual_queries: list[str] = field(default_factory=list)
    global_visual_queries: list[str] = field(default_factory=list)
    visual_intent: str = ""
    # --- vocabulário visual (retrocompatível: tudo opcional) ------------
    # `visual_type` decide a ESTRATÉGIA (foto, arte, diagrama, cartão);
    # `visual_entities`/`context` dão o que procurar; `forbidden` é a
    # lista de falsos positivos observados para o tema (ex.: "térmico"
    # puxando usina termelétrica). Tudo com default para que um
    # chapters.json antigo continue carregando sem erro.
    visual_type: str = "literal"
    subject: str = ""
    visual_entities: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Chapter":
        vtype = str(d.get("visual_type", "") or "").strip().lower()
        narration = str(d.get("narration", ""))
        if vtype not in VISUAL_TYPES:
            # chapters.json antigo (sem o campo) ou IA fora do formato:
            # deriva do texto em vez de assumir "literal" às cegas.
            vtype = classify_visual_type(narration) if vtype == "" else "literal"
        return cls(
            id=int(d.get("id", 0)),
            narration=narration,
            duration_estimate=float(d.get("duration_estimate", 0)),
            visual_queries=[str(q) for q in d.get("visual_queries", [])],
            global_visual_queries=[str(q) for q in d.get("global_visual_queries", [])],
            visual_intent=str(d.get("visual_intent", "")),
            visual_type=vtype,
            subject=str(d.get("subject", "") or ""),
            visual_entities=[str(q) for q in d.get("visual_entities", [])],
            context=[str(q) for q in d.get("context", [])],
            forbidden=[str(q) for q in d.get("forbidden", [])],
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
        vtype = classify_visual_type(narration)
        chapters.append(Chapter(
            id=len(chapters) + 1,
            narration=narration,
            duration_estimate=estimate_duration(narration),
            visual_queries=[],
            visual_intent="local fallback (sem consulta visual)",
            # Sem LLM não há consulta, mas a ESTRATÉGIA ainda é dedutível do
            # texto: uma cena que explica "como funciona" não deve receber
            # foto de laboratório, mesmo sem chave configurada.
            visual_type=vtype,
            subject="",
        ))
    return chapters


def _coerce_scene_list(data) -> list[dict]:
    """Extrai a lista de cenas de envelopes variados (nunca levanta KeyError).

    Aceita topo em lista ou dict com chaves `scenes` | `chapters` | `items`;
    ignora entradas que não sejam dict.
    """
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        candidates = None
        for key in ("scenes", "chapters", "items"):
            val = data.get(key)
            if isinstance(val, list) and val:
                candidates = val
                break
        if candidates is None:
            return []
    else:
        return []
    return [r for r in candidates if isinstance(r, dict)]


def _coerce_visual_terms(raw: dict) -> tuple[list[str], str]:
    """Normaliza os termos visuais preservando as FRASES.

    Três formatos chegam aqui e cada um precisa de um corte diferente:
    - lista ["thermal paper receipt", "receipt paper roll"] (novo): cada
      elemento JÁ é um termo completo com o contexto do tema. Juntar com
      espaço e separar por espaço devolveria 5 palavras soltas e
      duplicadas, que é o oposto do que a spec pede.
    - string com vírgula "a, b, c": separa pela vírgula.
    - string com espaço "water glass" (payload antigo): são 2 palavras
      independentes, então separar por espaço é o certo.
    """
    terms = raw.get("visual_search_terms", "")
    out: list[str] = []
    if isinstance(terms, list):
        for item in terms:
            s = str(item).strip()
            if s and s not in out:
                out.append(s)
    else:
        terms_str = str(terms or "").strip()
        if not terms_str:
            legacy = raw.get("visual_queries", [])
            if isinstance(legacy, list):
                terms_str = " ".join(str(t) for t in legacy).strip()
            else:
                terms_str = str(legacy or "").strip()
        if terms_str and ("," in terms_str or ";" in terms_str):
            out = [p.strip() for p in re.split(r"[,;]", terms_str) if p.strip()]
        else:
            out = terms_str.split()
    # Até 5 termos: a spec quer 3-5, e aceitar mais só traz ruído para o
    # scoring (e custo de rede).
    out = out[:5]
    return out, " ".join(out)


def _genre_forbidden(terms: list[str], genre: str) -> list[str]:
    """Proibições da IA + as que o perfil editorial impõe.

    A IA não sabe o que é enganoso para o gênero: "modern photograph" não
    é errado num vídeo de ciência e é péssimo num de história de uma
    pessoa. Quem sabe é o perfil.
    """
    from . import editorial
    perfil = editorial.get(genre)
    if perfil is None or not perfil.visual.forbidden:
        return terms
    out = list(terms)
    for t in perfil.visual.forbidden:
        if t not in out:
            out.append(t)
    return out[:8]


def _coerce_str_list(raw: dict, key: str, limit: int) -> list[str]:
    """Lista de strings em campo que a IA pode devolver como string solta."""
    val = raw.get(key, [])
    if isinstance(val, str):
        val = re.split(r"[,;]", val)
    if not isinstance(val, list):
        return []
    out = []
    for item in val:
        s = str(item).strip()
        if s:
            out.append(s)
    return out[:limit]


def _payload_snippet(data, limit: int = 300) -> str:
    """Resumo seguro do payload p/ diagnóstico (sem segredos: só saída do modelo)."""
    import json as _json
    try:
        text = _json.dumps(data, ensure_ascii=False)[:limit]
    except (TypeError, ValueError):
        text = str(data)[:limit]
    return text


def build_chapters(script: str, cfg: CurioConfig,
                   n_scenes: int | None = None, metrics=None,
                   genre: str = "", target_seconds: float | None = None,
                   genre_directive: str = "") -> tuple[list[Chapter], str]:
    """Retorna (capítulos, fonte). Fonte: 'openrouter:gemini-2.5-flash' | 'local'."""
    alvo = float(target_seconds) if target_seconds else None
    n_scenes = n_scenes or scenes_for_duration(cfg.duration_target,
                                               alvo or 9.0)
    lo, hi = max(3, n_scenes - 1), n_scenes + 1
    if nvidia_stage.any_llm_available():
        english = str(cfg.language or "").lower().startswith("en")
        system_prompt = (SCENES_SYSTEM_PROMPT_EN if english
                         else SCENES_SYSTEM_PROMPT)
        user_prompt = (f"Split this script into scenes:\n\n{script}"
                       if english else
                       f"Divida este roteiro em cenas:\n\n{script}")
        if genre_directive:
            # A direção do gênero entra no prompt da cena, não no roteiro:
            # é aqui que se decide o que a CENA tem que mostrar.
            system_prompt = system_prompt + "\n\n" + genre_directive
        data, label = nvidia_stage.complete_json(
            system_prompt.format(n=n_scenes, lo=lo, hi=hi),
            user_prompt,
            cfg.nvidia_model, cfg.nvidia_base_url, cfg.nvidia_timeout,
            metrics,
            or_model=cfg.openrouter_model, or_base_url=cfg.openrouter_base_url,
            extra=cfg.llm_overrides())
        provider = label.split(":")[0]
        raw_list = _coerce_scene_list(data)
        if not raw_list:
            print(f"AVISO: cenas {provider} vieram sem lista válida "
                  f"(payload: {_payload_snippet(data)}) — usando divisão local.",
                  file=sys.stderr)
        chapters = []
        for i, raw in enumerate(raw_list, 1):
            narration = str(raw.get("narration", "")).strip()
            if not narration:
                continue
            visual_queries, terms_str = _coerce_visual_terms(raw)
            vtype = str(raw.get("visual_type", "") or "").strip().lower()
            if vtype not in VISUAL_TYPES:
                # IA sem o campo (prompt antigo) ou valor fora do conjunto:
                # deriva do texto em vez de marcar tudo como literal.
                vtype = classify_visual_type(narration)
            chapters.append(Chapter(
                id=int(raw.get("index", raw.get("id", i)) or i),
                narration=narration,
                duration_estimate=estimate_duration(narration),
                visual_queries=visual_queries,
                global_visual_queries=visual_queries,
                visual_intent=terms_str,
                visual_type=vtype,
                subject=str(raw.get("subject", "") or "").strip(),
                visual_entities=_coerce_str_list(raw, "visual_entities", 4),
                context=_coerce_str_list(raw, "context", 3),
                forbidden=_genre_forbidden(_coerce_str_list(raw, "forbidden", 5),
                                          genre),
            ))
        if chapters and _norm(" ".join(c.narration for c in chapters)) == _norm(script):
            return chapters, provider
        print(f"AVISO: cenas {provider} não reproduzem o roteiro literal "
              f"(payload: {_payload_snippet(data)}) — usando divisão local.",
              file=sys.stderr)
    else:
        print("Sem chave OpenRouter: cenas por divisão local.", file=sys.stderr)
    return _local_chapters(script, n_scenes), "local"


def apply_timings(chapters: list[Chapter],
                  words: list[dict]) -> list[Chapter]:
    """Alinha capítulos aos WordBoundary reais por índice de palavra.

    Só os tempos mudam. O vocabulário visual (queries, tipo, entidades,
    proibições) é copiado inteiro: reconstruído a partir do dict em vez de
    listado campo a campo — assim qualquer campo novo sobrevive.
    """
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
        dados = ch.to_dict()
        dados.update(start=float(span[0]["start"]), end=float(span[-1]["end"]))
        out.append(Chapter.from_dict(dados))
        idx += n
    return out