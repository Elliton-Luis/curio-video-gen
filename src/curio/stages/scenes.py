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
from dataclasses import replace

from .. import textnorm
from ..config import CurioConfig
from . import nvidia as nvidia_stage
from .prompts import SCENES_SYSTEM_PROMPT, SCENES_SYSTEM_PROMPT_EN
from .scene_contract import (VISUAL_TYPES, ScenePlanResult, SemanticScene,
                             TimelineSpan, VideoContext, VisualRepresentation)
from .scene_representations import (
    _coerce_representations, _local_representation_rejections,
)
from .scene_visual_type import classify_visual_type

TARGET_SCENES = 5
WORDS_PER_MINUTE = 150


LEGACY_MAX_SCENES = 12          # teto de scenes_for_length sem gênero
LEGACY_MAX_SCENES_DURATION = 7  # teto de scenes_for_duration sem gênero


def scenes_for_duration(duration_target: float,
                        target_seconds: float = 9.0,
                        max_scenes: int | None = None) -> int:
    """~1 cena a cada `target_seconds`: 30 s→3, 45 s→5, 60 s→7 (3–7).

    Meta 0 (Automático) cai no piso: quem manda no nº de cenas é o
    tamanho do roteiro (ver `scenes_for_length`).

    `max_scenes=None` é o teto de sempre. Passar outro valor só é feito
    por um perfil de gênero, e é para isso que o parâmetro existe.
    """
    alvo = max(4.0, float(target_seconds or 9.0))
    teto = LEGACY_MAX_SCENES_DURATION if max_scenes is None else int(max_scenes)
    return max(3, min(teto, round(duration_target / alvo)))


def scenes_for_length(words: int, target_seconds: float = 9.0,
                      max_scenes: int | None = None) -> int:
    """Nº de cenas pelo TAMANHO do roteiro e o ALVO de segundos por cena.

    Usado no modo Automático e como piso em `script_input.scenes_for_script`:
    roteiro longo = mais cenas, nunca corte para caber em meta.

    `target_seconds` e `max_scenes` são os levers de pacing do gênero. É
    aqui que "cenas curtas e transformações frequentes" (etimologia,
    7,5 s) e "tempo suficiente para o diagrama ser compreendido"
    (ciência, 14 s) viram números de cena diferentes — e não adjetivos no
    prompt. Um perfil que não mexesse aqui seria exatamente o "rótulo que
    muda o texto".

    Sem gênero, `max_scenes=None` devolve o teto legado de 12 e o
    resultado é idêntico ao de antes dos perfis existirem. Estender o
    teto só para todo mundo mudaria o vídeo de quem não pediu nada.
    """
    est_seconds = max(1, words) / WORDS_PER_MINUTE * 60
    alvo = max(4.0, float(target_seconds or 9.0))
    teto = LEGACY_MAX_SCENES if max_scenes is None else int(max_scenes)
    return max(3, min(teto, round(est_seconds / alvo)))


# Palavras que, juntas, indicam latim. Uma sozinha não prova nada — "et"
# aparece em português em "e o et" — mas um conjunto delas numa frase curta
# é a assinatura da língua. A direção de arte pede que a frase em latim
# saia em itálico editorial, e sem esta detecção ela sairia na fonte da
# narração justamente na cena que existe para contrastar com ela.
_LATIN_HINTS = (
    "ora et labora", "ora pro nobis", "deus", "dominus", "labora", "laborare",
    "benedicta", "ora et", "in nomine", "ad maiorem", "gloria", "regula",
    "pax", "in domino", "servire", "obedientia", "caritas", "humilitas",
    "vanitas", "memento mori", "sine", "per ipsum", "ad maiora",
    "laudetur", "benedicat", "servite", "ora pro", "in pace", "requiescat",
    "sub lege", "sine metu", "timeo deum", "caro deo", "esto fidelis",
)

# Aspas: a cena traz uma fala de terceiro, que é voz de citação. A reta
# entra junto porque é a que o modelo de linguagem escreve, e sem ela a
# citação mais comum do mundo — a fala entre aspas retas — perderia o
# papel e sairia na fonte da narração.
_QUOTE_MARKS = ("“", "”", "«", "»", "„", '"', "\u201c")


def looks_latin(text: str) -> bool:
    """A frase é latim? Heurística deliberadamente conservadora."""
    t = " ".join(str(text or "").lower().split())
    if not t:
        return False
    if any(h in t for h in _LATIN_HINTS):
        return True
    # Três ou mais palavras de função latinas numa frase curta.
    funcoes = {"et", "in", "ad", "cum", "de", "ex", "non", "est", "sunt",
               "ut", "qui", "quod", "sed", "per", "pro", "cum", "deus",
               "dominus", "ora", "labora", "domini", "enim", "ita", "sine"}
    palavras = [p for p in t.replace(".", " ").replace(",", " ").split()
                if p]
    if len(palavras) > 12:
        return False
    return sum(1 for p in palavras if p in funcoes) >= 3


def derive_text_role(ch) -> str:
    """O papel tipográfico desta cena, quando ela não declarou nenhum.

    Só existe por retrocompatibilidade e por prudência: um
    `chapters.json` anterior ao recurso não tem `text_role`, e mesmo
    regerando as cenas o modelo esquece o campo com frequência. Sem esta
    derivação a feature-tipografia só funcionaria em projetos novos e
    completos, que é a pior forma de ela existir.

    A ordem vai do sinal mais forte ao mais fraco: aspas, latim, data,
    lugar, e o tipo visual como último recurso.
    """
    texto = " ".join([
        str(getattr(ch, "narration", "") or ""),
        str(getattr(ch, "subject", "") or "")])
    if any(m in texto for m in _QUOTE_MARKS):
        return "quote"
    idioma = str(getattr(ch, "text_language", "") or "").strip().lower()
    if idioma in ("la", "lat", "latim", "latin"):
        return "latin"
    if looks_latin(texto):
        return "latin"
    return ""


def text_role_for(ch, genre: str = "") -> str:
    """Papel efetivo da cena: o declarado, ou o derivado do conteúdo."""
    from .typography import ROLES
    declarado = str(getattr(ch, "text_role", "") or "").strip().lower()
    if declarado in ROLES:
        return declarado
    return derive_text_role(ch)




# Public compatibility export; internal producers/consumers import the projection
# from its owning module directly.
from .scene_projection import Chapter


def estimate_duration(narration: str, wpm: int = WORDS_PER_MINUTE) -> float:
    return max(2.5, round(len(narration.split()) / wpm * 60, 2))


def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"[^\w\s]", "", text)


def _local_semantic_scenes(script: str,
                           n_scenes: int = TARGET_SCENES
                           ) -> list[SemanticScene]:
    """Deterministic, narration-bounded semantic planner."""
    from . import subs as subs_stage
    sentences = subs_stage._sentences(script)
    if not sentences:
        raise ValueError("roteiro vazio — nada para dividir em cenas")
    from .scene_local_planning import local_visual_representations
    per = max(1, round(len(sentences) / n_scenes))
    scenes = []
    for i in range(0, len(sentences), per):
        narration = " ".join(sentences[i:i + per])
        vtype = classify_visual_type(narration)
        queries = local_visual_representations(narration)
        reps = []
        for term in queries:
            if re.match(r"^(battle|siege|revolution|war|conquest)\b", term, re.I):
                kind = "event"
            elif re.search(r"\bimp[eé]rio\b", term, re.I):
                kind = "empire"
            elif (re.search(rf"\b(king|queen|emperor|pope|rei|rainha|imperador|papa|born|portrait)\s+{re.escape(term)}\b",
                            narration, re.I)
                  or re.search(rf"\b(?:sob|under)\s+{re.escape(term.split(',')[0])}\b",
                               narration, re.I)
                  or re.search(rf"\b{re.escape(term.split(',')[0])}\b"
                               r"(?:\s+[A-ZÀ-Þ\w'-]+){0,2}\s+"
                               r"(?:cercou|derrotou|reconstruiu|governou|liderou|conquistou|patrocinou)\w*\b",
                               narration, re.I)):
                kind = "person"
            elif re.match(r"^(mesquita|catedral|templo|monument|mosque|cathedral|temple|monumento)\b",
                          term, re.I):
                kind = "monument"
            elif term.casefold() in {value.casefold() for value in
                                     re.findall(r"\b(?:jan[ií]zar\w+|soldad\w+|canh[oõ]es|espadas?|muralhas|fortalezas|navios?|frotas?|moedas|armas|est[aá]tuas|documentos|artefatos|monumentos|ex[eé]rcitos?|cavalarias?|uniformes?)\b",
                                                narration, re.I)}:
                kind = ("army" if re.match(
                    r"(jan[ií]zar|soldad|navio|frota|ex[eé]rcito|cavalaria|uniforme)",
                    term, re.I) else "artifact")
            else:
                kind = "entity"
            reps.append(VisualRepresentation(
                query=term, kind=kind, level=1,
                source="local_concrete_phrase"))
        scenes.append(SemanticScene(
            id=len(scenes) + 1,
            narration=narration,
            source="local",
            # Topic-level queries are added by enrichment once the canonical
            # video topic is known; local phrases remain scene-specific.
            global_visual_queries=(),
            visual_intent=("local fallback: " + " ".join(queries)).strip(),
            planning_mode="deterministic",
            # Sem LLM não há estratégia da IA, mas o vocabulário offline
            # ainda é dedutível: sem ele, o scoring compara título em
            # inglês com narração em português e reprova até a foto certa
            # (foi o que zerou "black hole" no vídeo de buracos negros).
            visual_type=vtype,
            subject=queries[0] if queries else "",
            visual_entities=tuple(queries[:4]),
            representations=tuple(reps),
            representation_rejections=tuple(
                _local_representation_rejections(narration)),
        ))
    for scene in scenes:
        errors = scene.contract_errors()
        if errors:
            raise ValueError(f"local planner emitted invalid scene: {errors}")
    return scenes


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


def _coerce_text_role(valor) -> str:
    """Aceita o papel que a IA deu, desde que seja um papel de verdade.

    A IA inventa nome de papel com frequência ("emphasis_quote",
    "TEXT_ROLE"), e papel inventado que passasse adiante renderizaria o
    texto na fonte errada sem ninguém saber por quê. Papel desconhecido
    vira vazio e a derivação por conteúdo assume.
    """
    from .typography import ROLES
    papel = str(valor or "").strip().lower().replace("-", "_").replace(" ", "_")
    if papel in ROLES:
        return papel
    # "serif_italic", "minion_pro" e afins: a IA respondeu com a RESPOSTA
    # em vez de a PERGUNTA. Não é papel, e não deve virar fonte.
    return ""


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


def _apply_video_context(scenes: list[SemanticScene], context
                         ) -> list[SemanticScene]:
    if not isinstance(context, dict):
        return scenes
    clean = {}
    for key in ("topic", "primary_entities", "secondary_entities", "places",
                "events", "period", "aliases"):
        value = context.get(key, [])
        if isinstance(value, str):
            value = value if key in ("topic", "period") else [value]
        if key in ("topic", "period"):
            clean[key] = str(value or "").strip()
        elif isinstance(value, list):
            clean[key] = [str(x).strip() for x in value if str(x).strip()][:12]
    return [replace(scene, video_context=VideoContext.from_value(clean))
            for scene in scenes]


def _repair_scene_count(scenes: list[SemanticScene], expected: int) -> bool:
    """Repair scene count using meaning contracts; never drop narration."""
    if not scenes or len(scenes) == expected:
        return False
    changed = False
    while len(scenes) > expected:
        compatible = []
        for index in range(len(scenes) - 1):
            left, right = scenes[index], scenes[index + 1]
            left_anchors = {textnorm.fold_phrase(value) for value in
                            (left.primary_entity, left.event, left.subject)
                            if value.strip()}
            right_anchors = {textnorm.fold_phrase(value) for value in
                             (right.primary_entity, right.event, right.subject)
                             if value.strip()}
            left_reps = {textnorm.fold_phrase(rep.query)
                         for rep in left.representations}
            right_reps = {textnorm.fold_phrase(rep.query)
                          for rep in right.representations}
            conflict = (left.event and right.event
                        and textnorm.fold_phrase(left.event)
                        != textnorm.fold_phrase(right.event))
            if not conflict and ((left_anchors & right_anchors)
                                 or (left_reps & right_reps)):
                compatible.append(index)
        if not compatible:
            break
        index = min(compatible, key=lambda pos:
                    len(scenes[pos].narration.split())
                    + len(scenes[pos + 1].narration.split()))
        left, right = scenes[index], scenes[index + 1]
        merged = {rep.query.casefold(): rep for rep in
                  (*left.representations, *right.representations)}
        scenes[index] = replace(
            left, narration=left.narration.rstrip() + " " + right.narration.lstrip(),
            subject_aliases=_combine(left.subject_aliases, right.subject_aliases),
            visual_entities=_combine(left.visual_entities, right.visual_entities),
            context=_combine(left.context, right.context),
            forbidden=_combine(left.forbidden, right.forbidden),
            visual_intent_structured=" / ".join(dict.fromkeys(
                value for value in (left.visual_intent_structured,
                                    right.visual_intent_structured) if value)),
            event=left.event or right.event,
            primary_entity=left.primary_entity or right.primary_entity,
            representations=tuple(list(merged.values())[:8]),
            global_visual_queries=_combine(
                left.global_visual_queries, right.global_visual_queries))
        scenes.pop(index + 1)
        changed = True
    while len(scenes) < expected:
        from . import subs as subs_stage
        options = []
        for index, scene in enumerate(scenes):
            sentences = subs_stage._sentences(scene.narration)
            if len(sentences) < 2:
                continue
            anchors = [scene.primary_entity, scene.event, scene.subject]
            anchors.extend(rep.query for rep in scene.representations)
            midpoint = len(sentences) // 2
            for split in range(1, len(sentences)):
                left_text = " ".join(sentences[:split])
                right_text = " ".join(sentences[split:])
                shared = next((anchor for anchor in anchors
                               if len(textnorm.tokens(str(anchor))) >= 2
                               and _contains_phrase(left_text, str(anchor))
                               and _contains_phrase(right_text, str(anchor))), "")
                if shared:
                    options.append((abs(split - midpoint), index, split,
                                    sentences, scene))
                    break
        if not options:
            break
        _, index, split, sentences, scene = min(options)
        left = replace(scene, narration=" ".join(sentences[:split]))
        right = replace(scene, narration=" ".join(sentences[split:]))
        scenes[index:index + 1] = [left, right]
        changed = True
    if not changed:
        return False
    for index, scene in enumerate(scenes, 1):
        scenes[index - 1] = replace(scene, id=index)
    return True


def _combine(left, right) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*left, *right)))


def _contains_phrase(text: str, phrase: str) -> bool:
    hay = f" {textnorm.fold_phrase(text)} "
    needle = textnorm.fold_phrase(phrase)
    return bool(needle and f" {needle} " in hay)


def _repair_scene_narration(scenes: list[SemanticScene], script: str
                            ) -> tuple[list[SemanticScene], bool]:
    """Restore exact script spans when scene narration is a close paraphrase.

    The planner supplies scene boundaries and intent. This alignment replaces
    only narration with source sentences, and rejects weak/ambiguous mappings.
    """
    from . import subs as subs_stage
    sentences = subs_stage._sentences(script)
    if not scenes or len(sentences) < len(scenes):
        return scenes, False
    stop = textnorm.STOP_PT | textnorm.STOP_EN
    scene_terms = [set(textnorm.tokens(scene.narration)) - stop for scene in scenes]
    sentence_terms = [set(textnorm.tokens(sentence)) - stop for sentence in sentences]
    cursor, scores, repaired = 0, [], []
    for index, scene in enumerate(scenes):
        remaining_scenes = len(scenes) - index - 1
        max_end = len(sentences) - remaining_scenes
        target_len = max(1, round(len(sentences) / len(scenes)))
        best = None
        for end in range(cursor + 1, max_end + 1):
            source_terms = set().union(*sentence_terms[cursor:end])
            model_terms = scene_terms[index]
            union = source_terms | model_terms
            overlap = len(source_terms & model_terms) / max(1, len(union))
            score = overlap - 0.035 * abs((end - cursor) - target_len)
            if best is None or score > best[0]:
                best = (score, end, overlap)
        if best is None or best[2] < 0.22:
            return scenes, False
        scores.append(best[2])
        repaired.append(replace(
            scene, narration=" ".join(sentences[cursor:best[1]])))
        cursor = best[1]
    if (cursor != len(sentences) or sum(scores) / len(scores) < 0.38
            or _norm(" ".join(scene.narration for scene in repaired))
            != _norm(script)):
        return scenes, False
    return repaired, True


def _payload_snippet(data, limit: int = 300) -> str:
    """Resumo seguro do payload p/ diagnóstico (sem segredos: só saída do modelo)."""
    import json as _json
    try:
        text = _json.dumps(data, ensure_ascii=False)[:limit]
    except (TypeError, ValueError):
        text = str(data)[:limit]
    return text


def build_semantic_scenes(script: str, cfg: CurioConfig,
                          n_scenes: int | None = None, metrics=None,
                          genre: str = "", target_seconds: float | None = None,
                          genre_directive: str = "",
                          max_scenes: int | None = None) -> ScenePlanResult:
    """Plan and validate meaning; return semantics beside time spans."""
    scenes, source = _plan_semantic_rows(
        script, cfg, n_scenes=n_scenes, metrics=metrics, genre=genre,
        target_seconds=target_seconds, genre_directive=genre_directive,
        max_scenes=max_scenes)
    return ScenePlanResult(
        semantic_scenes=tuple(scenes),
        timeline_spans=tuple(TimelineSpan(scene.id,
                                          estimate_duration(scene.narration))
                             for scene in scenes),
        source=source)


def build_local_semantic_scenes(script: str,
                                n_scenes: int = TARGET_SCENES) -> ScenePlanResult:
    """Deterministic planner returns the same semantic/timing contract."""
    scenes = _local_semantic_scenes(script, n_scenes)
    return ScenePlanResult(
        semantic_scenes=tuple(scenes),
        timeline_spans=tuple(TimelineSpan(scene.id,
                                          estimate_duration(scene.narration))
                             for scene in scenes),
        source="local")


def _plan_semantic_rows(script: str, cfg: CurioConfig,
                        n_scenes: int | None = None, metrics=None,
                        genre: str = "", target_seconds: float | None = None,
                        genre_directive: str = "",
                        max_scenes: int | None = None
                        ) -> tuple[list[SemanticScene], str]:
    """Parse and repair planner output using semantic contracts only."""
    alvo = float(target_seconds) if target_seconds else None
    from ..runlog import event as run_event
    n_scenes = n_scenes or scenes_for_duration(cfg.duration_target,
                                               alvo or 9.0, max_scenes)
    lo, hi = max(3, n_scenes - 1), n_scenes + 1
    video_context = {}
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
        run_event("provider", f"Cenas: {label}", operation="scenes",
                  provider=provider, model=label.split(":", 1)[-1])
        raw_list = _coerce_scene_list(data)
        video_context = data.get("video_context", {}) if isinstance(data, dict) else {}
        if not raw_list:
            logged = run_event("fallback", f"Cenas {provider}: resposta sem lista; divisão local",
                               operation="scenes", fallback="local",
                               response_shape="no scene list")
            if not logged:
                print(f"AVISO: cenas {provider} vieram sem lista válida "
                      f"(payload: {_payload_snippet(data)}) — usando divisão local.",
                      file=sys.stderr)
        semantic_scenes = []
        for i, raw in enumerate(raw_list, 1):
            narration = str(raw.get("narration", "")).strip()
            if not narration:
                continue
            try:
                scene_id = int(raw.get("index", raw.get("id", i)) or i)
            except (TypeError, ValueError):
                scene_id = i
            visual_queries, terms_str = _coerce_visual_terms(raw)
            representations = _coerce_representations(raw.get("representations", []))
            if not visual_queries and representations:
                visual_queries = [item["query"] for item in representations[:5]]
                terms_str = " ".join(visual_queries)
            normalized_representations = tuple(
                representation for index, item in enumerate(representations)
                if (representation := VisualRepresentation.from_value(item, index)))
            if not normalized_representations and visual_queries:
                normalized_representations = tuple(VisualRepresentation(
                    query=query, kind="related", level=index,
                    source="llm_visual_search_term")
                    for index, query in enumerate(visual_queries))
            visual_queries = [rep.query for rep in normalized_representations]
            vtype = str(raw.get("visual_type", "") or "").strip().lower()
            if vtype not in VISUAL_TYPES:
                # IA sem o campo (prompt antigo) ou valor fora do conjunto:
                # deriva do texto em vez de marcar tudo como literal.
                vtype = classify_visual_type(narration)
            semantic_scenes.append(SemanticScene(
                id=scene_id, narration=narration, source=provider,
                planning_mode="llm", visual_type=vtype,
                subject=str(raw.get("subject", "") or "").strip(),
                visual_entities=tuple(_coerce_str_list(raw, "visual_entities", 4)),
                context=tuple(_coerce_str_list(raw, "context", 3)),
                forbidden=tuple(_genre_forbidden(
                    _coerce_str_list(raw, "forbidden", 5), genre)),
                visual_intent=terms_str,
                visual_intent_structured=str(raw.get("visual_intent", "") or "").strip(),
                primary_entity=str(raw.get("primary_entity", raw.get("subject", "")) or "").strip(),
                event=str(raw.get("event", "") or "").strip(),
                place=str(raw.get("place", "") or "").strip(),
                period=str(raw.get("period", "") or "").strip(),
                representations=normalized_representations,
                global_visual_queries=tuple(visual_queries),
                text_role=_coerce_text_role(raw.get("text_role")),
                text_language=str(raw.get("text_language", "") or "").strip().lower(),
            ))
        narration_repaired = False
        if semantic_scenes and _norm(" ".join(c.narration for c in semantic_scenes)) != _norm(script):
            semantic_scenes, narration_repaired = _repair_scene_narration(
                semantic_scenes, script)
        if semantic_scenes and _norm(" ".join(c.narration for c in semantic_scenes)) == _norm(script):
            repaired = _repair_scene_count(semantic_scenes, n_scenes)
            semantic_scenes = _apply_video_context(semantic_scenes, video_context)
            errors = [scene.contract_errors() for scene in semantic_scenes]
            if any(errors):
                raise ValueError("scene planner produced invalid semantic scene")
            if repaired or narration_repaired:
                run_event("result", f"Cenas {provider}: estrutura reparada",
                          operation="scenes", expected=n_scenes,
                          scenes=len(semantic_scenes),
                          repair=[*(["merge_adjacent"] if repaired else []),
                                  *(["restore_source_spans"] if narration_repaired else [])])
            return semantic_scenes, provider
        logged = run_event("fallback", f"Cenas {provider}: narração não reproduz roteiro; divisão local",
                           operation="scenes", fallback="local",
                           validation="narration mismatch",
                           returned_scenes=len(semantic_scenes))
        if not logged:
            print(f"AVISO: cenas {provider} não reproduzem o roteiro literal "
                  f"(payload: {_payload_snippet(data)}) — usando divisão local.",
                  file=sys.stderr)
    else:
        logged = run_event("fallback", "Cenas: sem provider; divisão local",
                           operation="scenes", fallback="local",
                           reason="no provider key")
        if not logged:
            print("Sem chave OpenRouter: cenas por divisão local.", file=sys.stderr)
    local = build_local_semantic_scenes(script, n_scenes)
    semantic_scenes = _apply_video_context(
        list(local.semantic_scenes), video_context)
    return semantic_scenes, "local"
