"""Regras de seleção de mídia: o que uma imagem precisa ter para entrar.

Este módulo é a parte que decide, não a parte que busca. Ele responde a
três perguntas, sempre nesta ordem:

1. **Eliminações** — licença, resolución, tamanho: a imagem é utilizável?
2. **Bloqueios temáticos** — o título carrega "wallpaper", "4k", ou um termo
   que a própria cena declarou proibido? Aí é decoração, não conteúdo.
3. **Termos decorativos globais** — independentes do tema.

O ponto 3 e o ponto 2 não podem ser o mesmo filtro. "wallpaper" é sempre
erro; "power plant" só é erro numa cena sobre papel térmico. Confundir os
dois foi o que produziu usina termelétrica em vídeo de recibo: o filtro
que existia era genérico, e o que faltava era específico do tema.

Nada aqui consulta o provedor: os metadados vêm do `MediaAsset`.
"""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlsplit

from .. import textnorm

# --- termos decorativos: sempre errados -------------------------------
# Observados em produção: "papel de parede de montanha/rio/campo/deserto"
# com "wallpaper", "4k", "hd" nas tags. São fundo de tela, não conteúdo.
# Lista deliberadamente curta e sem "text"/"typography": texto numa imagem
# pode ser o próprio assunto da cena (uma etiqueta, um recibo, uma placa).
DECORATIVE_TERMS = (
    "wallpaper", "wall paper", "wallpapers", "background", "backgrounds",
    "backdrop", "desktop", "screensaver", "screen saver",
    "template", "mockup", "mock up", "mock-up", "psd", "ai generated",
    "4k", "8k", "uhd", "hdr photo", "stock photo", "royalty free",
    "logo", "logos", "watermark", "screenshot", "banner", "collage",
    "border design", "frame border", "placeholder", "dummy text",
)

# "4k"/"hd" soltos wouldiam derrubar "4Kids" ou "HDRI"; exige fronteira de
# palavra e, para os numéricos, que não sejam parte de outro token.
_WORD_CACHE: dict[str, re.Pattern] = {}


def _pattern(term: str) -> re.Pattern:
    """Regex com fronteiras de palavra, memorizada (o filtro roda por candidato)."""
    pat = _WORD_CACHE.get(term)
    if pat is None:
        esc = re.escape(term).replace(r"\ ", r"\s+")
        pat = re.compile(rf"(?<![a-z0-9]){esc}(?![a-z0-9])", re.I)
        _WORD_CACHE[term] = pat
    return pat


# Comparar "imperdível" com "imperdivel" (minúsculas sem acento) é a mesma
# conta que o scoring e a pesquisa fazem; a implementação mora em
# `curio.textnorm`.
_fold = textnorm.fold


# --- termos negativos da cena -----------------------------------------

def scene_forbidden(ch) -> list[str]:
    """Termos proibidos da cena + acréscimos automáticos.

    A IA devolve `forbidden` (os falsos positivos que ela anticipates). Não
    não fica só nisso: o tipo de visual implica bloqueios que nenhuma IA
    precisa adivinhar. Uma cena `historical_art` não pode receber foto
    moderna de stock, e `mechanism` não deve ser \"resolvida\" com uma
    foto genérica de laboratório.
    """
    out: list[str] = []
    identities = [set(_fold(name).split()) for name in
                  [getattr(ch, "subject", ""), *(getattr(ch, "subject_aliases", []) or [])] if name]
    for term in list(getattr(ch, "forbidden", []) or []):
        s = str(term).strip()
        if s and any(set(_fold(s).split()).issubset(identity) for identity in identities):
            continue  # Contradictory cached model metadata must not veto its own subject.
        if s and s not in out:
            out.append(s)
    vtype = str(getattr(ch, "visual_type", "") or "literal")
    context = _fold(" ".join(getattr(ch, "subject_aliases", []) or []) + " " +
                    str(getattr(ch, "narration", "") or ""))
    if (_fold(getattr(ch, "subject", "")) == "medusa" and
            any(term in context for term in ("mitolog", "gorgona", "gorgon"))):
        out.extend(["jellyfish", "sea jelly", "cnidarian", "medusa-phase"])
    if vtype == "historical_art":
        out.extend(_dedup(["modern photo", "stock photo", "contemporary"]))
    elif vtype == "mechanism":
        out.extend(_dedup(["stock laboratory", "generic laboratory"]))
    elif vtype == "typographic":
        # A cena é uma palavra: foto de banco não serve, nem de raspão.
        out.extend(_dedup(["wallpaper", "generic background"]))
    if _is_space_scene(ch):
        out.extend(_dedup(list(_SPACE_FORBIDDEN)))
    return out


# Bloqueio automático para cena espacial: foto de bancada não representa
# o céu, e "Mars Science Laboratory" é o rover em Marte, não um laboratório.
_SPACE_FORBIDDEN = (
    "laboratory", "microscope", "test tube", "petri dish",
    "Mars Science Laboratory",
)


def _is_space_scene(ch) -> bool:
    """A cena é sobre espaço/astronomia?

    Usa os marcadores de `textnorm`, os mesmos da busca de mídia e do
    classificador de cena. Ter três listas aqui foi como o vídeo de buraco
    negro acabou com bancada: cada estágio reconhecia um conjunto
    diferente do que os outros dois.
    """
    return textnorm.is_space_topic(" ".join([
        str(getattr(ch, "narration", "") or ""),
        str(getattr(ch, "subject", "") or ""),
        " ".join(list(getattr(ch, "visual_queries", []) or [])),
        " ".join(list(getattr(ch, "visual_entities", []) or [])),
        " ".join(list(getattr(ch, "context", []) or [])),
    ]))


def _dedup(terms) -> list[str]:
    seen, out = set(), []
    for t in terms:
        k = t.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    return out


def scene_blocklist(ch) -> list[str]:
    """Lista completa de proibições: decorativas globais + termos da cena."""
    return _dedup(list(DECORATIVE_TERMS) + scene_forbidden(ch))


# --- decisão -----------------------------------------------------------

def rejection_reason(asset: dict, blocked: list[str]) -> str:
    """Motivo da rejeição, ou "" se a imagem passa nos filtros temáticos.

    Devolver o MOTIVO (e não um booleano) é o que permite a folha de
    contato explicar ao autor por que a usina não entrou — sem isso, o
    autor só vê que a cena ficou sem foto e não sabe corrigir.
    """
    # Só o título é lido de propósito. Tags do provedor são o que produziu
    # os falsos positivos: "wallpaper, 4k, hd" numa cena de conteúdo.
    title = _fold(str(asset.get("title", "") or ""))
    if not title:
        return ""  # sem título não há base para julgar; o filtro final decide
    for term in blocked:
        if term and _pattern(_fold(term)).search(title):
            return f"título contém termo bloqueado: {term!r}"
    return ""


def min_dimension() -> int:
    """Lado mínimo em px após o recorte vertical 1080x1920.

    O render recorta e amplia, então a fonte precisa de pelo menos a
    largura final. 1080 é o piso; 1000 (valor anterior) produzia fotos que
    borravam exatamente na vertical.
    """
    try:
        return max(320, int(os.environ.get("CURIO_MEDIA_MIN_DIMENSION", "1080")))
    except ValueError:
        return 1080


def is_image_url(url: str) -> bool:
    """Reconhece extensão de imagem ou formato explícito do CDN Unsplash."""
    if re.search(r"\.(jpe?g|png|webp)(\?|$)", url or "", re.I):
        return True
    parsed = urlsplit(url or "")
    return (parsed.scheme == "https" and parsed.hostname == "images.unsplash.com"
            and parse_qs(parsed.query).get("fm") == ["jpg"])


def passes_hard_filters(asset: dict, blocked: list[str],
                        max_bytes: int = 25 * 1024 * 1024) -> str:
    """Filtros eliminatórios de metadados. Devolve "" ou o motivo.

    Não baixa nada e não chama rede: decide sobre o que o provedor já
    devolveu. Dimensões desconhecidas (0) passam — há provedores (NASA) que
    não as informam, e a conferência real acontece pós-download via ffprobe.
    """
    if not asset.get("download_url"):
        return "sem URL de download"
    if not is_image_url(asset["download_url"]):
        return "não é imagem (jpg/png/webp)"
    floor = min_dimension()
    w, h = int(asset.get("width") or 0), int(asset.get("height") or 0)
    if w > 0 and h > 0 and min(w, h) < floor:
        return f"resolução {w}x{h} menor que {floor}px"
    size = int(asset.get("size_bytes") or 0)
    if size and size > max_bytes:
        return f"arquivo {size // 1024}KB acima do teto"
    return rejection_reason(asset, blocked)
