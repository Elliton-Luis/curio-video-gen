"""Pontuação de relevância em camadas.

A camada `base` é lexical e roda em qualquer máquina, sem GPU, sem modelo,
sem rede — é ela que garante que o `curio` funcione como sempre. As camadas
`clip` e `vision` são pontos de extensão: plugáveis, desligadas por padrão,
e o pipeline continua completo sem elas (item 8 da spec: CLIP não é
obrigatório).

Por que pontuar em vez de "pegar o primeiro": a busca devolve o que o
provedor acha relevante para a PALAVRA, não para a CENA. "thermal" devolve
usina termelétrica com pontuação alta do provedor. A nota aqui compara a
descrição da foto com o vocabulário da cena, e devolve o motivo quando a
nota é baixa — assim a folha de contato consegue explicar a troca.
"""

from __future__ import annotations

from .. import textnorm

# A nota é 0–100 e se divide em duas parcelas que NÃO competem entre si:
# o núcleo prova o que a cena É (até 75) e o apoio mostra o que foi
# pedido como pista (até 25). Sem essa separação, uma imagem que acerta o
# assunto e uma que acerta assunto + apoio davam as duas 100 e o desempate
# sumia — que é justamente o que o bônus existe para fazer.
CORE_MAX = 75.0
BONUS_MAX = 25.0
BASE_MAX = 100.0

# Score abaixo do qual a imagem não é usada e a cena troca de estratégia.
DEFAULT_THRESHOLD = 34.0


# A normalização e a tokenização vivem em `curio.textnorm`: são a MESMA
# comparação de texto que a pesquisa e o filtro de mídia fazem, e manter
# cópia própria foi o que deixou `scoring` casando "File:Saint…" de um
# jeito e a busca de outro.
_fold = textnorm.fold
_tokens = textnorm.tokens


def _scene_terms(ch) -> tuple[dict[str, float], dict[str, float]]:
    """Vocabulário da cena em duas camadas: NÚCLEO e APOIO.

    Núcleo = o que define o que a cena É: o `subject` declarado, ou as
    consultas quando não há subject, ou a narração como último recurso.

    Apoio = o que pode estar na cena sem ser o assunto: entidades e
    contexto. Entra como BÔNUS, não no denominador. Misturar os dois fazia
    uma pintura Correta reprovar: a cena pedia fresco, monge e passarinho,
    a imagem era o santo, e o denominador inteiro contava os três que não
    estavam lá. O sujeito certo não pode ser diluído por pistas.
    """
    core: dict[str, float] = {}
    support: dict[str, float] = {}

    def _add(bucket, text, weight):
        for tok in _tokens(str(text or "")):
            bucket[tok] = max(bucket.get(tok, 0.0), weight)

    _add(core, getattr(ch, "subject", ""), 3.0)
    _add(core, getattr(ch, "primary_entity", ""), 4.0)
    _add(core, getattr(ch, "event", ""), 4.0)
    if not core:
        for term in list(getattr(ch, "visual_queries", []) or []):
            _add(core, term, 2.0)
    for term in list(getattr(ch, "visual_entities", []) or []):
        _add(support, term, 2.0)
    for term in list(getattr(ch, "context", []) or []):
        _add(support, term, 1.0)
    if not core:
        # Sem vocabulário declarado: a narração é a única fonte. Narração é
        # contexto, não assunto, então cada palavra entra com o mesmo peso.
        _add(core, getattr(ch, "narration", ""), 1.0)
    return core, support


def _candidate_text(asset: dict) -> str:
    """Use structured provider evidence; absent metadata stays absent."""
    parts = [asset.get(key, "") for key in
             ("title", "description", "date_created", "media_type")]
    for key in ("tags", "categories"):
        values = asset.get(key, []) or []
        parts.extend([values] if isinstance(values, str) else values)
    return textnorm.fold_phrase(" ".join(str(x) for x in parts if x))


def _candidate_fields(asset: dict) -> dict[str, str]:
    fields = {"title": str(asset.get("title", "") or ""),
              "description": str(asset.get("description", "") or ""),
              "date": str(asset.get("date_created", "") or ""),
              "media_type": str(asset.get("media_type", asset.get("kind", "")) or "")}
    for key, label in (("tags", "tags"), ("categories", "categories")):
        values = asset.get(key, []) or []
        fields[label] = " ".join([values] if isinstance(values, str)
                                  else [str(x) for x in values])
    return {key: textnorm.fold_phrase(value) for key, value in fields.items()}


def _has_phrase(text: str, phrase: str) -> bool:
    phrase = textnorm.fold_phrase(phrase)
    # Single-token matches are not identity proof: Mercury, Java, Roman and
    # Mass each have common unrelated referents.
    if len(phrase.split()) < 2:
        return False
    return f" {phrase} " in f" {text} "


def semantic_relevance(asset: dict, ch) -> dict:
    """Independent topic/scene evidence from complete phrases in metadata."""
    context = dict(getattr(ch, "video_context", {}) or {})
    if not context:
        return {"topic_relevance": None, "scene_relevance": None,
                "topic_matches": [], "scene_matches": [],
                "topic_evidence": {}, "scene_evidence": {},
                "metadata_support": 0.0}
    text = _candidate_text(asset)
    fields = _candidate_fields(asset)

    def evidence_for(phrases):
        evidence = {}
        for phrase in phrases:
            phrase = str(phrase or "").strip()
            if not phrase:
                continue
            matching_fields = [name for name, content in fields.items()
                               if _has_phrase(content, phrase)]
            if matching_fields:
                evidence[phrase] = matching_fields
        return evidence

    topic_phrases = [context.get("topic", "")]
    for key in ("primary_entities", "secondary_entities", "events", "places",
                "aliases", "period"):
        values = context.get(key, []) or []
        topic_phrases.extend([values] if isinstance(values, str) else values)
    topic_evidence = evidence_for(topic_phrases)
    topic_matches = list(topic_evidence)
    scene_phrases = [getattr(ch, "visual_intent_structured", "")]
    if str(getattr(ch, "visual_intent", "") or "").startswith("local fallback"):
        # Local query phrases are the only scene plan when the LLM is down.
        # Match complete phrases only; one-token homonyms remain non-evidence.
        scene_phrases.extend(getattr(ch, "visual_queries", []) or [])
    # Legacy plans without an explicit visual representation use the event
    # name as scene evidence. Structured plans keep event/topic relation
    # separate from evidence of what the candidate actually depicts.
    has_scene_plan = bool(getattr(ch, "representations", [])
                          or getattr(ch, "visual_intent_structured", ""))
    if not has_scene_plan:
        scene_phrases.append(getattr(ch, "event", ""))
    for key in ("representations", "visual_entities"):
        values = getattr(ch, key, []) or []
        if key == "representations":
            scene_phrases.extend(
                str(item.get("query", "")) for item in values if isinstance(item, dict))
        else:
            scene_phrases.extend(values)
    scene_evidence = evidence_for(scene_phrases)
    scene_matches = list(scene_evidence)
    if not topic_matches and scene_matches:
        # The structured representation is itself an explicit relation to
        # this video topic. This supports one-word topics without allowing
        # their bare ambiguous token to prove identity.
        topic_matches = [f"representation:{scene_matches[0]}"]
    evidence_strength = {"title": 100.0, "description": 90.0,
                         "categories": 75.0, "tags": 60.0,
                         "date": 40.0, "media_type": 35.0,
                         "title_contextual_representation": 50.0,
                         "metadata_contextual_representation": 35.0}
    topic = max((evidence_strength.get(field, 0.0)
                 for values in topic_evidence.values() for field in values),
                default=(100.0 if topic_matches and not topic_evidence else 0.0))
    scene = max((evidence_strength.get(field, 0.0)
                 for values in scene_evidence.values() for field in values),
                default=(100.0 if scene_matches and not scene_evidence else 0.0))
    if topic_matches and not scene_matches:
        # Contextual portraits/maps/artifacts are valid fallback media. A
        # bare homonym or product title is not. Type words are generic visual
        # forms, not subject-specific blacklist rules.
        contextual_forms = ("portrait", "bust", "statue", "painting", "engraving",
                            "relief", "column", "sculpture", "monument", "coin",
                            "map", "mapping", "document", "artifact", "artefact", "illustration",
                            "manuscript", "photograph", "mission")
        tokens = set(textnorm.tokens(text))
        title_tokens = set(textnorm.tokens(fields.get("title", "")))
        form = next((kind for kind in contextual_forms
                     if kind in title_tokens), "")
        direct_title_form = bool(form)
        if not form:
            form = next((kind for kind in contextual_forms
                         if kind in tokens), "")
        if form:
            scene = 50.0 if direct_title_form else 35.0
            scene_matches = [f"contextual representation:{form}"]
            scene_evidence[scene_matches[0]] = [
                "title_contextual_representation" if direct_title_form
                else "metadata_contextual_representation"]
    provenance = {
        "provider": str(asset.get("provider", "") or ""),
        "creator": str(asset.get("author", "") or "")[:120],
        "source_url": str(asset.get("source_url", "") or "")[:300],
        "date_created": str(asset.get("date_created", "") or "")[:80],
        "media_type": str(asset.get("media_type", asset.get("kind", "")) or ""),
    }
    # Metadata breadth affects quality only after topic/scene evidence exists.
    support_weights = {"title": 2.0, "description": 1.5, "categories": 1.0,
                       "tags": 0.5, "date": 0.5, "media_type": 0.5}
    evidence_fields = set().union(*(set(v) for v in scene_evidence.values())) \
        if scene_evidence else set()
    metadata_support = min(5.0, sum(support_weights.get(x, 0.0)
                                    for x in evidence_fields))
    if any(topic_evidence.values()) or any(scene_evidence.values()):
        metadata_support += min(1.0, 0.25 * sum(bool(asset.get(key)) for key in
                              ("provider", "author", "source_url")))
    return {"topic_relevance": topic, "scene_relevance": scene,
            "topic_matches": topic_matches[:5],
            "scene_matches": scene_matches[:5],
            "topic_evidence": {k: v for k, v in list(topic_evidence.items())[:5]},
            "scene_evidence": {k: v for k, v in list(scene_evidence.items())[:5]},
            "metadata_support": metadata_support, **provenance}


def base_score(asset: dict, ch) -> dict:
    """Score deterministic text evidence; structured context needs phrases.

    Legacy chapters use lexical coverage across available provider metadata.
    Structured chapters first require independent topic and scene evidence
    from full phrases in title, description, tags, categories, dates, or type.
    Provider/creator/source metadata can add bounded quality support only
    after relevance exists. Text metadata does not prove image pixels.

    Nota = cobertura do núcleo (0–100) + bônus por apoio encontrado
    (teto de 25). A cobertura do núcleo é o que decide: ela responde "isto
    é mesmo a coisa da cena". O bônus desempata favor de quem mostra
    também o que foi pedido como apoio.

    Devolve {"score", "matched", "missing"} para o relatório.
    """
    core, support = _scene_terms(ch)
    if not core:
        return {"score": 0.0, "matched": [], "missing": []}
    title_tokens = set(_tokens(_candidate_text(asset)))
    if not title_tokens:
        # Sem título não há como provar relevância. Não é 0 automático: a
        # camada opcional (visão) ainda pode avaliar, se existir.
        return {"score": 0.0, "matched": [], "missing": list(core)[:6]}

    if not topic_anchor_matches(asset, ch):
        sem = semantic_relevance(asset, ch)
        return {"score": 0.0, "matched": [],
                "missing": list(core)[:6], "support": [], **sem,
                "semantic_rejection": "video topic anchor mismatch"}
    sem = semantic_relevance(asset, ch)
    if sem["topic_relevance"] is not None:
        if not sem["topic_matches"] or sem["topic_relevance"] < 65:
            return {"score": 0.0, "matched": [], "missing": list(core)[:6],
                    "support": [], **sem,
                    "semantic_rejection": ("no topic evidence" if not sem["topic_matches"]
                                           else "insufficient topic metadata evidence")}
        contextual_scene = any(str(match).startswith("contextual representation:")
                               for match in sem["scene_matches"])
        if sem["scene_relevance"] < 65 and not contextual_scene:
            return {"score": 0.0, "matched": [], "missing": list(core)[:6],
                    "support": [], **sem,
                    "semantic_rejection": ("no scene evidence" if not sem["scene_matches"]
                                           else "insufficient scene metadata evidence")}
    if str(getattr(ch, "visual_intent", "") or "").startswith("local fallback"):
        # Local scene may ask for context (e.g. `Armenia war`) while the
        # video subject is a person (`Marcus Aurelius`). An image of the
        # person is valid across scenes; score local terms plus video anchor.
        for anchor in list(getattr(ch, "global_visual_queries", []) or []):
            for token in _tokens(anchor):
                core[token] = max(core.get(token, 0.0), 3.0)

    def _hits(terms: dict[str, float]) -> tuple[float, list[str], list[str]]:
        hit, matched, missing = 0.0, [], []
        for tok, weight in terms.items():
            if tok in title_tokens:
                hit += weight
                matched.append(tok)
            else:
                missing.append(tok)
        return hit, matched, missing

    hit_core, matched, missing = _hits(core)
    total_core = sum(core.values()) or 1.0
    coverage = hit_core / total_core
    aliases = getattr(ch, "subject_aliases", []) or []
    # Aliases completos vêm da entidade pesquisada ou de um lugar literal da
    # cena. Não aumentar nota por sobrenome isolado ou homônimo de uma query.
    if aliases:
        alias_matches = [set(_tokens(alias)) for alias in aliases
                         if _tokens(alias)]
        full = next((tokens for tokens in alias_matches
                     if tokens.issubset(title_tokens)), None)
        if full is None:
            coverage = 0.0
        else:
            coverage = 1.0
            matched = sorted(full)
    base = CORE_MAX * coverage

    # Bônus de apoio: entidade presente vale 10, contexto vale 5, teto 25.
    # O apoio desempata a favor de quem mostra também o que foi pedido
    # como pista, mas NÃO compra uma imagem errada: só entra se o núcleo
    # já prova o assunto (≥50% de cobertura). Sem essa trava, "thermal
    # power station" casava com o sujeito "thermal receipt paper" numa
    # palavra e o bônus empurrava a usina por cima do corte — exatamente
    # o falso positivo que esta camada existe para impedir.
    matched_sup = [t for t in support if t in title_tokens]
    bonus = 0.0
    if coverage >= 0.5:
        bonus = min(BONUS_MAX, sum(w for t, w in support.items()
                                   if t in title_tokens) * 5.0)
    score = round(min(BASE_MAX, base + bonus), 2)
    if sem["topic_relevance"] is not None:
        semantic_score = (sem["scene_relevance"] * 0.7
                          + sem["topic_relevance"] * 0.3)
        score = round(min(100.0, semantic_score + sem.get("metadata_support", 0.0)), 2)
    return {"score": score,
            "matched": matched, "missing": missing[:6],
            "support": matched_sup[:6], **sem,
            "bonus": round(bonus, 2), "base_score": round(base, 2)}


def topic_anchor_matches(asset: dict, ch) -> bool:
    """Require local-fallback image title to identify the whole video topic.

    A local scene only has a short phrase (`mass`, `nation`, `sun`). Those
    nouns alone collide with bus station, country flags and landscapes.
    Local topic anchor is a full phrase such as `black hole` or `French
    Revolution`; at least one anchor phrase must occur in title tokens.
    AI-authored scenes keep existing scoring behavior.
    """
    if not str(getattr(ch, "visual_intent", "") or "").startswith("local fallback"):
        return True
    anchors = [*list(getattr(ch, "global_visual_queries", []) or []),
               *textnorm.topic_phrases(
                   str(getattr(ch, "narration", "") or ""))]
    if not anchors:
        return True
    title_tokens = set(_tokens(_candidate_text(asset)))
    phrases = [set(_tokens(anchor)) for anchor in anchors]
    phrases = [phrase for phrase in phrases if phrase]
    return not phrases or any(phrase.issubset(title_tokens) for phrase in phrases)


def generic_score(asset: dict, query: str) -> dict:
    """Nota de candidato genérico contra o próprio termo buscado.

    Foto de igreja entra porque mostra igreja, não porque finge ser o
    assunto da cena. Mesmo mínimo das específicas; sem veto de aliases.
    """
    from types import SimpleNamespace
    pseudo = SimpleNamespace(subject=query, visual_queries=[],
                             visual_entities=[], context=[])
    return base_score(asset, pseudo)


def below_threshold(entries: list[dict],
                    threshold: float = DEFAULT_THRESHOLD) -> tuple[list, list]:
    """Separa o que passa do mínimo do que não passa.

    Regra da spec: se o melhor candidato ficar abaixo do limite, NÃO se usa
    o "menos ruim" — a cena troca de estratégia visual. Sem esta etapa o
    ranking era decorativo: ordenava bem e mesmo assim empacotava o
    primeiro disponível, que era justamente a imagem irrelevante que o
    ranking tinha posto por último.
    """
    ok, low = [], []
    for entry in entries:
        (ok if float(entry.get("score", 0.0)) >= threshold else low).append(entry)
    return ok, low


def threshold() -> float:
    """Mínimo de relevância, configurável por env (0 desliga o corte)."""
    import os
    try:
        return max(0.0, min(100.0, float(
            os.environ.get("CURIO_MEDIA_SCORE_MIN", str(DEFAULT_THRESHOLD)))))
    except ValueError:
        return DEFAULT_THRESHOLD


def clip_status(cfg=None) -> str | None:
    """Se a camada CLIP pode rodar, e em que device. None = indisponível.

    Não baixa nada e não instala nada. Se as bibliotecas não estiverem
    presentes, devolve None e o pipeline segue só com a base — é o
    comportamento padrão, não um erro.
    """
    import importlib.util
    if not clip_enabled(cfg):
        return None
    if importlib.util.find_spec("open_clip") is None:
        return "habilitada, mas open_clip não está instalado (pip install 'curio[clip]')"
    if importlib.util.find_spec("torch") is None:
        return "habilitada, mas torch não está instalado (pip install 'curio[clip]')"
    try:
        import torch  # noqa: PLC0415 — importado só se habilitado
        dev = clip_device(cfg)
        if dev == "cpu" and not clip_cpu_allowed(cfg):
            return "habilitada, sem acelerador; configure CURIO_CLIP_DEVICE=cpu para permitir CPU"
        return f"habilitada (device={dev}, torch {torch.__version__})"
    except Exception as exc:  # noqa: BLE001 — status nunca derruba o doctor
        return f"habilitada, mas falhou ao inicializar: {exc}"


def clip_enabled(cfg=None) -> bool:
    """CLIP só entra se ligado no config/env. Desligado é o padrão."""
    import os
    raw = os.environ.get("CURIO_CLIP_ENABLED")
    if raw is not None and raw.strip():
        return raw.strip().lower() in ("1", "true", "s", "sim", "on", "yes")
    return bool(getattr(cfg, "visual_clip_enabled", False))


def clip_device(cfg=None) -> str:
    """Device preferencial, sem CUDA como única hipótese.

    `auto` procura, nesta ordem, aceleradores que existam de fato no
    torch instalado: XPU (Intel, o caso do Arc B580 do autor), CUDA e MPS.
    Sem nenhum, devolve `cpu` — e a camada só roda em CPU se a política
    configurada permitir, para não transformar um vídeo rápido em lento.
    """
    import os
    import importlib.util
    # Opção explícita PRIMEIRO: quem pediu `device = "xpu"` quer xpu, e a
    # detecção automática não tem o direito de responder "cpu" por não ter
    # encontrado nada. Verificar o torch antes disso fazia a configuração
    # explícita ser ignorada justamente quando ela é a que importa.
    env_want = os.environ.get("CURIO_CLIP_DEVICE", "").strip().lower()
    want = (env_want if env_want in ("auto", "xpu", "cuda", "mps", "cpu")
            else getattr(cfg, "visual_clip_device", "auto") or "auto").lower()
    if want != "auto":
        return want
    if importlib.util.find_spec("torch") is None:
        return "cpu"
    try:
        import torch  # noqa: PLC0415 — importado só se existir
        for attr in ("xpu", "cuda", "mps"):
            backend = getattr(torch, attr, None)
            is_avail = getattr(backend, "is_available", None)
            try:
                if backend is not None and is_avail and is_avail():
                    return attr
            except Exception:  # noqa: BLE001 — backend problemático = pula
                continue
    except Exception:  # noqa: BLE001 — torch quebrado: cai para cpu
        pass
    return "cpu"


def clip_cpu_allowed(cfg=None) -> bool:
    import os
    env_device = os.environ.get("CURIO_CLIP_DEVICE", "").strip().lower()
    raw = os.environ.get("CURIO_CLIP_ALLOW_CPU")
    allow = (raw.strip().lower() in ("1", "true", "yes", "sim", "on")
             if raw is not None else bool(getattr(cfg, "visual_clip_allow_cpu", False)))
    return env_device == "cpu" or getattr(cfg, "visual_clip_device", "") == "cpu" or allow


_CLIP_RUNTIME = None


def clip_score_image(path: str, ch, cfg=None) -> float | None:
    """Cosine similarity for one shortlisted image; CLIP never searches."""
    global _CLIP_RUNTIME
    if not clip_enabled(cfg):
        return None
    device = clip_device(cfg)
    if device == "cpu" and not clip_cpu_allowed(cfg):
        return None
    if _CLIP_RUNTIME is False:
        return None
    try:
        import open_clip
        import torch
        from PIL import Image
        if _CLIP_RUNTIME is None:
            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="laion2b_s34b_b79k", device=device)
            model.eval()
            _CLIP_RUNTIME = (model, preprocess, open_clip.get_tokenizer("ViT-B-32"), device)
        model, preprocess, tokenizer, device = _CLIP_RUNTIME
    except Exception:
        _CLIP_RUNTIME = False
        return None
    try:
        scene_text = [str(getattr(ch, "visual_intent_structured", "") or ""),
                      str(getattr(ch, "event", "") or ""),
                      str(getattr(ch, "primary_entity", "") or ""),
                      str(getattr(ch, "subject", "") or "")]
        scene_text.extend(str(item.get("query", "")) for item in
                          (getattr(ch, "representations", []) or [])
                          if isinstance(item, dict))
        context = dict(getattr(ch, "video_context", {}) or {})
        scene_text.extend([str(context.get("topic", "")),
                           str(context.get("period", ""))])
        prompt = ". ".join(dict.fromkeys(x.strip() for x in scene_text if x.strip()))
        if not prompt:
            return None
        image = preprocess(Image.open(path).convert("RGB")).unsqueeze(0).to(device)
        text = tokenizer([prompt]).to(device)
        with torch.inference_mode():
            image_features = model.encode_image(image)
            text_features = model.encode_text(text)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            return float((image_features @ text_features.T).item())
    except Exception:
        return None


def rank_candidates(candidates: list[dict], ch) -> list[dict]:
    """Ordena por score de texto e registra evidência decomponível.

    The opt-in CLIP reranker operates downstream on the approved shortlist.

    Empate é desfeito pela ordem de chegada, o que mantém o resultado
    determinístico para o mesmo conjunto de candidatos — importante para
    o cache e para o `--dry-run` não mentirem entre execuções.
    """
    for i, entry in enumerate(candidates):
        info = base_score(entry.get("asset") or {}, ch)
        entry["score"] = info["score"]
        entry["score_detail"] = {
            "base": info["score"],
            "matched": info["matched"],
            "missing": info["missing"],
            "topic_relevance": info.get("topic_relevance"),
            "scene_relevance": info.get("scene_relevance"),
            "topic_matches": info.get("topic_matches", []),
            "scene_matches": info.get("scene_matches", []),
            "topic_evidence": info.get("topic_evidence", {}),
            "scene_evidence": info.get("scene_evidence", {}),
            "metadata_support": info.get("metadata_support", 0.0),
            "provider": info.get("provider", ""),
            "creator": info.get("creator", ""),
            "source_url": info.get("source_url", ""),
            "date_created": info.get("date_created", ""),
            "media_type": info.get("media_type", ""),
            "bonus": info.get("bonus", 0.0),
            "semantic_rejection": info.get("semantic_rejection", ""),
            # Registro de qual camada decidiu: hoje só base, mas a
            # folha de contato mostra a coluna mesmo assim para não
            # precisar mudar de layout quando CLIP entrar.
            "layers": ["base"],
        }
        entry["_i"] = i
    return sorted(candidates, key=lambda e: (-e["score"], e["_i"]))
