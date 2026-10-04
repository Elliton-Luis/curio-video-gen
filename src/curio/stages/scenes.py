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

from .. import textnorm
from ..config import CurioConfig
from . import nvidia as nvidia_stage
from .prompts import SCENES_SYSTEM_PROMPT, SCENES_SYSTEM_PROMPT_EN

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

    Usado no modo Automático e como piso no `visual.scenes_for_script`:
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


VISUAL_TYPES = ("literal", "mechanism", "historical_art", "conceptual",
                "typographic")

# Sinais de que a cena explica um PROCESSO, não uma coisa. Uma foto de
# laboratório não mostra "o calor altera o corante" — mostra um frasco.
# Reconhecer isso é o que evita a foto genérica no lugar do diagrama.
_MECHANISM_HINTS_PT = (
    "como funciona", "como faz", "por que funciona", "o que acontece quando",
    "acontece quando", "passo a passo", "etapas", "processo",
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
    "batalha", "battle", "cerco", "siege", "revolução", "revolution",
    "guerra", "war", "conquista", "conquest", "frota", "fleet",
    "janízaro", "janizaro", "janissary", "janissaries", "exército",
    "exercito", "army", "cavalaria", "cavalry",
)
# Sinais de que a cena é melhor dita com palavras e não com imagem.
_TYPOGRAPHIC_HINTS = (
    "quer dizer", "significa", "significado", "vem do latim", "vem do",
    "etimologia", "etimológica", "etimologicamente", "chama-se", "chamava",
    "o termo", "a palavra", "definicao", "definição", "etimolog",
    "significa literalmente", "means", "derived from", "etymology",
    "word comes from", "literally",
)


# Sinais de tópico espacial: a cena é sobre o céu, não sobre história.
# Sem esta guarda, "Isso não é um mito de ficção científica" virava
# `historical_art` por causa de "mito" — e o vídeo de buraco negro ia
# parar em acervo de igreja em vez de telescópio. O conjunto é o mesmo da
# busca e do gate de imagem (`textnorm.is_space_topic`): três listas
# diferentes garantiriam uma delas errada.
_SPACE_HINTS = textnorm.SPACE_MARKERS

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
    if any(h in text for h in _TYPOGRAPHIC_HINTS):
        return "typographic"
    if textnorm.is_space_topic(text):
        return "literal"
    if any(h in text for h in _MECHANISM_HINTS_PT + _MECHANISM_HINTS_EN):
        return "mechanism"
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
    subject_aliases: list[str] = field(default_factory=list)
    visual_entities: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    # Shared video context and explicit director output. Optional for old
    # chapters.json files; queries are generated from representations first.
    video_context: dict = field(default_factory=dict)
    visual_intent_structured: str = ""
    primary_entity: str = ""
    event: str = ""
    place: str = ""
    period: str = ""
    representations: list[dict] = field(default_factory=list)
    representation_rejections: list[dict] = field(default_factory=list)
    # --- papel tipográfico (retrocompatível: tudo opcional) -------------
    # A cena declara a FUNÇÃO do texto, nunca a fonte: `text_role="quote"`
    # significa "isto é uma citação", e quem decide que em `people` citação
    # é itálico serifado é o perfil, em stages/typography.py. Pedir a fonte
    # aqui quebraria a abstração no instante em que o gênero muda, e trocar
    # de gênero é justamente o que precisa ser barato.
    # Vazio = a cena nao reservou papel; o papel vem da derivacao por conteudo.
    text_role: str = ""
    # "la" quando o texto é latim. O papel `latin` é o que entrega o
    # itálico editorial para a frase em latim, e é o caso que a direção de
    # arte do projeto cita primeiro.
    text_language: str = ""
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
            # deriva o texto em vez de assumir "literal" às cegas.
            vtype = classify_visual_type(narration) if vtype == "" else "literal"
        from .typography import ROLES
        visual_queries, visual_query_rejections = _validate_query_list(
            d.get("visual_queries", []))
        global_queries, global_query_rejections = _validate_query_list(
            d.get("global_visual_queries", []))
        papel = str(d.get("text_role", "") or "").strip().lower()
        if papel not in ROLES:
            # chapters.json antigo não tem o campo, e a IA às vezes inventa
            # um papel. Papel desconhecido é descartado, e a derivação pelo
            # conteúdo assume — um papel errado renderiza o texto na fonte
            # errada sem nenhuma pista de por quê.
            papel = ""
        return cls(
            id=int(d.get("id", 0)),
            narration=narration,
            duration_estimate=float(d.get("duration_estimate", 0)),
            visual_queries=visual_queries,
            global_visual_queries=global_queries,
            visual_intent=str(d.get("visual_intent", "")),
            visual_type=vtype,
            subject=str(d.get("subject", "") or ""),
            subject_aliases=[str(q) for q in d.get("subject_aliases", [])],
            visual_entities=[str(q) for q in d.get("visual_entities", [])],
            context=[str(q) for q in d.get("context", [])],
            forbidden=[str(q) for q in d.get("forbidden", [])],
            video_context=(dict(d.get("video_context") or {})
                           if isinstance(d.get("video_context"), dict) else {}),
            visual_intent_structured=str(d.get("visual_intent_structured", "") or ""),
            primary_entity=str(d.get("primary_entity", "") or ""),
            event=str(d.get("event", "") or ""),
            place=str(d.get("place", "") or ""),
            period=str(d.get("period", "") or ""),
            representations=_coerce_representations(d.get("representations", [])),
            representation_rejections=(
                list(d.get("representation_rejections", []) or [])[:20]
                + _rejected_representations(d.get("representations", []))
                + visual_query_rejections + global_query_rejections),
            text_role=papel,
            text_language=str(d.get("text_language", "") or "").strip().lower(),
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
    try:
        from .visual import local_queries as _local_queries
    except Exception:  # noqa: BLE001 — sem queries, sem vocabulário
        _local_queries = None
    per = max(1, round(len(sentences) / n_scenes))
    chapters = []
    for i in range(0, len(sentences), per):
        narration = " ".join(sentences[i:i + per])
        vtype = classify_visual_type(narration)
        queries: list[str] = []
        if _local_queries is not None:
            try:
                queries = [q for q in (_local_queries(narration) or []) if q][:5]
            except Exception:  # noqa: BLE001 — query nunca é fatal
                queries = []
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
            reps.append({"query": term, "kind": kind, "level": 1,
                         "source": "local_concrete_phrase"})
        chapters.append(Chapter(
            id=len(chapters) + 1,
            narration=narration,
            duration_estimate=estimate_duration(narration),
            visual_queries=list(queries),
            global_visual_queries=list(queries),
            visual_intent=("local fallback: " + " ".join(queries)).strip(),
            # Sem LLM não há estratégia da IA, mas o vocabulário offline
            # ainda é dedutível: sem ele, o scoring compara título em
            # inglês com narração em português e reprova até a foto certa
            # (foi o que zerou "black hole" no vídeo de buracos negros).
            visual_type=vtype,
            subject=queries[0] if queries else "",
            visual_entities=list(queries[:4]),
            representations=reps,
            representation_rejections=_local_representation_rejections(narration),
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


def _coerce_representations(raw) -> list[dict]:
    """Normalize visual representations without splitting their phrases."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:8]:
        if isinstance(item, dict):
            query = str(item.get("query", item.get("visual", item.get("name", ""))) or "").strip()
            if query:
                kind = str(item.get("kind", "related") or "related").lower()
                if _representation_rejection_reason(query, kind):
                    continue
                try:
                    level = int(item.get("level", len(out)) or 0)
                except (TypeError, ValueError):
                    level = len(out)
                out.append({"query": query,
                            "kind": str(item.get("kind", "related") or "related"),
                            "level": level,
                            "source": str(item.get("source", "planner") or "planner")})
        else:
            query = str(item or "").strip()
            if query and not _representation_rejection_reason(query, "related"):
                out.append({"query": query, "kind": "related", "level": len(out)})
    return out


def _validate_query_list(raw) -> tuple[list[str], list[dict]]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return [], []
    accepted, rejected = [], []
    for value in raw[:12]:
        query = str(value or "").strip()
        reason = _representation_rejection_reason(query, "related")
        if reason:
            rejected.append({"query": query, "kind": "related", "reason": reason})
        elif query and query.casefold() not in {item.casefold() for item in accepted}:
            accepted.append(query)
    return accepted, rejected


_VISUAL_ORDINALS = {"primeira", "primeiro", "segunda", "segundo", "first",
                    "second", "third", "initial", "next", "former"}
_VISUAL_ABSTRACTIONS = {"gold", "ouro", "power", "elite"}


def _representation_rejection_reason(query: str, kind: str) -> str:
    """Reject isolated narration fragments before they become search anchors."""
    folded = textnorm.fold_phrase(query)
    words = folded.split()
    if len(words) == 1 and folded in _VISUAL_ORDINALS:
        return "isolated_ordinal"
    if len(words) == 1 and folded in _VISUAL_ABSTRACTIONS:
        return "isolated_abstract_or_material"
    if len(words) == 1 and re.search(
            r"(?:avam|ariam|eram|iram|ando|endo|indo|aram|ou|eu|iu)$", folded):
        return "isolated_inflected_verb"
    if len(words) == 1 and kind in {"related", "entity"} and folded in textnorm.VISUAL_STOP_PT:
        return "isolated_stopword"
    return ""


def _rejected_representations(raw) -> list[dict]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    rejected = []
    for item in raw[:20]:
        query = str(item.get("query", item.get("visual", item.get("name", "")))
                    if isinstance(item, dict) else item or "").strip()
        kind = str(item.get("kind", "related") or "related") if isinstance(item, dict) else "related"
        reason = _representation_rejection_reason(query, kind)
        if reason:
            rejected.append({"query": query, "kind": kind, "reason": reason})
    return rejected


def _local_representation_rejections(narration: str) -> list[dict]:
    rejected = []
    for word in re.findall(r"[A-Za-zÀ-ÿ]+", narration):
        normalized = textnorm.fold_phrase(word)
        reason = _representation_rejection_reason(normalized, "related")
        if reason and not any(row["query"] == normalized for row in rejected):
            rejected.append({"query": normalized, "kind": "related", "reason": reason})
    return rejected[:20]


def _apply_video_context(chapters: list[Chapter], context) -> None:
    if not isinstance(context, dict):
        return
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
    for chapter in chapters:
        chapter.video_context = clean


def _repair_scene_count(chapters: list[Chapter], expected: int) -> bool:
    """Repair count only after exact narration validation; never drop words."""
    if not chapters or len(chapters) == expected:
        return False
    changed = False
    while len(chapters) > expected:
        # Merge only adjacent scenes sharing a declared visual anchor.
        compatible = []
        for i in range(len(chapters) - 1):
            left, right = chapters[i], chapters[i + 1]
            left_anchors = {textnorm.fold_phrase(x) for x in
                            [left.primary_entity, left.event, left.subject]
                            if str(x or "").strip()}
            right_anchors = {textnorm.fold_phrase(x) for x in
                             [right.primary_entity, right.event, right.subject]
                             if str(x or "").strip()}
            left_reps = {textnorm.fold_phrase(x.get("query", ""))
                         for x in left.representations}
            right_reps = {textnorm.fold_phrase(x.get("query", ""))
                          for x in right.representations}
            event_conflict = (left.event and right.event
                              and textnorm.fold_phrase(left.event)
                              != textnorm.fold_phrase(right.event))
            if not event_conflict and ((left_anchors & right_anchors)
                                       or (left_reps & right_reps)):
                compatible.append(i)
        if not compatible:
            break
        i = min(compatible, key=lambda n: len(chapters[n].narration.split())
                + len(chapters[n + 1].narration.split()))
        left, right = chapters[i], chapters[i + 1]
        left.narration = (left.narration.rstrip() + " " + right.narration.lstrip())
        for name in ("visual_queries", "global_visual_queries", "visual_entities",
                     "context", "forbidden", "subject_aliases"):
            setattr(left, name, list(dict.fromkeys(getattr(left, name)
                                                   + getattr(right, name))))
        left.representations = list({item["query"]: item for item in
                                    left.representations + right.representations}.values())[:8]
        left.visual_intent_structured = " / ".join(dict.fromkeys(
            x for x in (left.visual_intent_structured,
                        right.visual_intent_structured) if x))
        if not left.event:
            left.event = right.event
        if not left.primary_entity:
            left.primary_entity = right.primary_entity
        chapters.pop(i + 1)
        changed = True
    while len(chapters) < expected:
        from . import subs as subs_stage
        options = []
        for index, chapter in enumerate(chapters):
            sentences = subs_stage._sentences(chapter.narration)
            if len(sentences) < 2:
                continue
            anchors = [chapter.primary_entity, chapter.event, chapter.subject]
            anchors.extend(rep.get("query", "") for rep in chapter.representations)
            mid = len(sentences) // 2
            for split in range(1, len(sentences)):
                left_text, right_text = " ".join(sentences[:split]), " ".join(sentences[split:])
                shared_anchor = next((anchor for anchor in anchors
                                      if len(textnorm.tokens(str(anchor))) >= 2
                                      and _contains_phrase(left_text, str(anchor))
                                      and _contains_phrase(right_text, str(anchor))), "")
                if shared_anchor:
                    options.append((abs(split - mid), index, split,
                                    sentences, chapter))
                    break
        if not options:
            break
        _, index, split, sentences, chapter = min(options)
        left = Chapter.from_dict(chapter.to_dict())
        right = Chapter.from_dict(chapter.to_dict())
        left.narration = " ".join(sentences[:split])
        right.narration = " ".join(sentences[split:])
        chapters[index:index + 1] = [left, right]
        changed = True
    if not changed:
        return False
    for i, chapter in enumerate(chapters, 1):
        chapter.id = i
    return changed


def _contains_phrase(text: str, phrase: str) -> bool:
    hay = f" {textnorm.fold_phrase(text)} "
    needle = textnorm.fold_phrase(phrase)
    return bool(needle and f" {needle} " in hay)


def _repair_scene_narration(chapters: list[Chapter], script: str) -> bool:
    """Restore exact script spans when scene narration is a close paraphrase.

    The planner supplies scene boundaries and intent. This alignment replaces
    only narration with source sentences, and rejects weak/ambiguous mappings.
    """
    from . import subs as subs_stage
    sentences = subs_stage._sentences(script)
    if not chapters or len(sentences) < len(chapters):
        return False
    stop = textnorm.STOP_PT | textnorm.STOP_EN
    chapter_terms = [set(textnorm.tokens(ch.narration)) - stop for ch in chapters]
    sentence_terms = [set(textnorm.tokens(sentence)) - stop for sentence in sentences]
    cursor, scores = 0, []
    for index, chapter in enumerate(chapters):
        remaining_chapters = len(chapters) - index - 1
        max_end = len(sentences) - remaining_chapters
        target_len = max(1, round(len(sentences) / len(chapters)))
        best = None
        for end in range(cursor + 1, max_end + 1):
            source_terms = set().union(*sentence_terms[cursor:end])
            model_terms = chapter_terms[index]
            union = source_terms | model_terms
            overlap = len(source_terms & model_terms) / max(1, len(union))
            score = overlap - 0.035 * abs((end - cursor) - target_len)
            if best is None or score > best[0]:
                best = (score, end, overlap)
        if best is None or best[2] < 0.22:
            return False
        scores.append(best[2])
        chapter.narration = " ".join(sentences[cursor:best[1]])
        cursor = best[1]
    if cursor != len(sentences) or sum(scores) / len(scores) < 0.38:
        return False
    return _norm(" ".join(ch.narration for ch in chapters)) == _norm(script)


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
                   genre_directive: str = "",
                   max_scenes: int | None = None) -> tuple[list[Chapter], str]:
    """Retorna (capítulos, fonte). Fonte: 'openrouter:gemini-2.5-flash' | 'local'."""
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
        chapters = []
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
            vtype = str(raw.get("visual_type", "") or "").strip().lower()
            if vtype not in VISUAL_TYPES:
                # IA sem o campo (prompt antigo) ou valor fora do conjunto:
                # deriva do texto em vez de marcar tudo como literal.
                vtype = classify_visual_type(narration)
            chapters.append(Chapter(
                id=scene_id,
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
                visual_intent_structured=str(raw.get("visual_intent", "") or "").strip(),
                primary_entity=str(raw.get("primary_entity", raw.get("subject", "")) or "").strip(),
                event=str(raw.get("event", "") or "").strip(),
                place=str(raw.get("place", "") or "").strip(),
                period=str(raw.get("period", "") or "").strip(),
                representations=representations,
                text_role=_coerce_text_role(raw.get("text_role")),
                text_language=str(raw.get("text_language", "") or "").strip().lower(),
            ))
        narration_repaired = False
        if chapters and _norm(" ".join(c.narration for c in chapters)) != _norm(script):
            narration_repaired = _repair_scene_narration(chapters, script)
        if chapters and _norm(" ".join(c.narration for c in chapters)) == _norm(script):
            repaired = _repair_scene_count(chapters, n_scenes)
            _apply_video_context(chapters, video_context)
            if repaired or narration_repaired:
                run_event("result", f"Cenas {provider}: estrutura reparada",
                          operation="scenes", expected=n_scenes,
                          scenes=len(chapters),
                          repair=[*(["merge_adjacent"] if repaired else []),
                                  *(["restore_source_spans"] if narration_repaired else [])])
            return chapters, provider
        logged = run_event("fallback", f"Cenas {provider}: narração não reproduz roteiro; divisão local",
                           operation="scenes", fallback="local",
                           validation="narration mismatch",
                           returned_scenes=len(chapters))
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
    chapters = _local_chapters(script, n_scenes)
    _apply_video_context(chapters, video_context)
    return chapters, "local"


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
