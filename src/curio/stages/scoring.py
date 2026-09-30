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

import unicodedata

# Peso máximo que a base lexical pode dar. Deixa a porta aberta para uma
# camada semântica somar por cima sem que a base "vença sempre".
BASE_MAX = 100.0

# Score abaixo do qual a imagem não é usada e a cena troca de estratégia.
DEFAULT_THRESHOLD = 34.0


def _fold(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def _tokens(text: str) -> list[str]:
    """Palavras útiles de um texto: sem acento, sem ruído de 1-2 letras."""
    out = []
    for raw in _fold(text).replace(",", " ").replace(";", " ").split():
        word = raw.strip("._-()[]")
        if len(word) >= 3:
            out.append(word)
    return out


def _scene_terms(ch) -> dict[str, float]:
    """Vocabulário da cena ponderado: o que PODE aparecer e o que DEVE.

    `subject` e `visual_entities` valem mais que `context`: contexto é
    cenário ("cash register"), entidade é o assunto ("receipt"). A
    ponderação é o que faz "cash register" não superar "receipt".
    """
    weights: dict[str, float] = {}

    def _add(text, weight: float) -> None:
        for tok in _tokens(str(text or "")):
            weights[tok] = max(weights.get(tok, 0.0), weight)

    _add(getattr(ch, "subject", ""), 3.0)
    for term in list(getattr(ch, "visual_queries", []) or []):
        _add(term, 2.0)
    for term in list(getattr(ch, "visual_entities", []) or []):
        _add(term, 2.0)
    for term in list(getattr(ch, "context", []) or []):
        _add(term, 1.0)
    if not weights:
        # Sem vocabulário declarado: a narração é a única fonte. Narração é
        # contexto, não assunto, então cada palavra entra com o mesmo peso.
        _add(getattr(ch, "narration", ""), 1.0)
    return weights


def base_score(asset: dict, ch) -> dict:
    """Camada base: sobreposição entre o vocabulário da cena e o título.

    Só o título. Tag é palpite de quem doou o acervo — foi exatamente ela
    que trouxe "wallpaper, 4k" e "power plant" para uma cena de papel
    térmico. Um título é a descrição da foto; quando o título não diz nada
    do assunto, a nota é baixa e a imagem não entra.

    Devolve {"score", "matched", "missing"} para o relatório.
    """
    terms = _scene_terms(ch)
    if not terms:
        return {"score": 0.0, "matched": [], "missing": []}
    title_tokens = set(_tokens(str(asset.get("title", "") or "")))
    if not title_tokens:
        # Sem título não há como provar relevância. Não é 0 automático: a
        # camada opcional (visão) ainda pode avaliar, se existir.
        return {"score": 0.0, "matched": [], "missing": list(terms)[:6]}
    hit = 0.0
    possible = sum(terms.values())
    matched, missing = [], []
    for tok, weight in terms.items():
        if tok in title_tokens:
            hit += weight
            matched.append(tok)
        else:
            missing.append(tok)
    score = BASE_MAX * (hit / possible) if possible else 0.0
    return {"score": round(score, 2), "matched": matched, "missing": missing[:6]}


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
