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


def base_score(asset: dict, ch) -> dict:
    """Camada base: o título descreve a cena?

    Só o título. Tag é palpite de quem doou o acervo — foi exatamente ela
    que trouxe "wallpaper, 4k" e "power plant" para uma cena de papel
    térmico. Um título é a descrição da foto; quando o título não diz nada
    do assunto, a nota é baixa e a imagem não entra.

    Nota = cobertura do núcleo (0–100) + bônus por apoio encontrado
    (teto de 25). A cobertura do núcleo é o que decide: ela responde "isto
    é mesmo a coisa da cena". O bônus desempata favor de quem mostra
    também o que foi pedido como apoio.

    Devolve {"score", "matched", "missing"} para o relatório.
    """
    core, support = _scene_terms(ch)
    if not core:
        return {"score": 0.0, "matched": [], "missing": []}
    title_tokens = set(_tokens(str(asset.get("title", "") or "")))
    if not title_tokens:
        # Sem título não há como provar relevância. Não é 0 automático: a
        # camada opcional (visão) ainda pode avaliar, se existir.
        return {"score": 0.0, "matched": [], "missing": list(core)[:6]}

    if not topic_anchor_matches(asset, ch):
        return {"score": 0.0, "matched": [],
                "missing": list(core)[:6], "support": []}
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
    return {"score": round(min(BASE_MAX, base + bonus), 2),
            "matched": matched, "missing": missing[:6],
            "support": matched_sup[:6]}


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
    anchors = list(getattr(ch, "global_visual_queries", []) or [])
    if not anchors:
        return True
    title_tokens = set(_tokens(str(asset.get("title", "") or "")))
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


def clip_status() -> str | None:
    """Se a camada CLIP pode rodar, e em que device. None = indisponível.

    Não baixa nada e não instala nada. Se as bibliotecas não estiverem
    presentes, devolve None e o pipeline segue só com a base — é o
    comportamento padrão, não um erro.
    """
    import importlib.util
    if not clip_enabled():
        return None
    if importlib.util.find_spec("open_clip") is None:
        return "habilitada, mas open_clip não está instalado (pip install video-gen[clip])"
    if importlib.util.find_spec("torch") is None:
        return "habilitada, mas torch não está instalado (pip install video-gen[clip])"
    try:
        import torch  # noqa: PLC0415 — importado só se habilitado
        dev = clip_device()
        if dev == "cpu":
            return f"habilitada, mas sem aceleração disponível (device={dev})"
        return f"habilitada (device={dev}, torch {torch.__version__})"
    except Exception as exc:  # noqa: BLE001 — status nunca derruba o doctor
        return f"habilitada, mas falhou ao inicializar: {exc}"


def clip_enabled() -> bool:
    """CLIP só entra se ligado no config/env. Desligado é o padrão."""
    import os
    raw = os.environ.get("CURIO_CLIP_ENABLED", "")
    if raw:
        return raw.strip().lower() in ("1", "true", "s", "sim", "on", "yes")
    return False


def clip_device() -> str:
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
    want = (os.environ.get("CURIO_CLIP_DEVICE", "auto") or "auto").lower()
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


def rank_candidates(candidates: list[dict], ch) -> list[dict]:
    """Ordena candidatos por nota final (base agora; CLIP/vision depois).

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
            # Registro de qual camada decidiu: hoje só base, mas a
            # folha de contato mostra a coluna mesmo assim para não
            # precisar mudar de layout quando CLIP entrar.
            "layers": ["base"],
        }
        entry["_i"] = i
    return sorted(candidates, key=lambda e: (-e["score"], e["_i"]))
