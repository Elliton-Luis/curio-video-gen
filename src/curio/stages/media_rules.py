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
from ..media.providers import (MAX_BYTES, classify_rights, license_ok,
                                min_dimension as providers_min_dimension)

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


# O piso de resolução é resolvido em `media/providers.py`, que é onde o
# filtro roda na busca; reexportar aqui mantém a regra legível a quem decide
# no gate. Duas constantes para a mesma medida foi o que deixou uma foto de
# 1023px passar na busca e ser rejeitada depois.
min_dimension = providers_min_dimension


def is_image_url(url: str) -> bool:
    """Reconhece extensão de imagem ou formato explícito do CDN Unsplash."""
    if re.search(r"\.(jpe?g|png|webp)(\?|$)", url or "", re.I):
        return True
    parsed = urlsplit(url or "")
    return (parsed.scheme == "https" and parsed.hostname == "images.unsplash.com"
            and parse_qs(parsed.query).get("fm") == ["jpg"])


def asset_gate_reason(asset: dict, blocked: list[str],
                      max_bytes: int | None = None) -> str:
    """O gate único de uma imagem: "" se pode entrar, o motivo se não pode.

    Antes havia três implementações da mesma ideia — `_validate_asset`
    (booleano, só no `visual.py`), `_validate_asset_for` (motivo, no
    `visual.py`) e `passes_hard_filters` (motivo, aqui) — com divergências
    reais: uma delas nem checava licença, e o piso de resolução vinha de
    duas constantes diferentes. Três cópias de um gate não é refatoração,
    é três oportunidades de o mesmo gate aprovar imagens diferentes.

    A ordem das decisões é a que o autor precisa ler: URL, formato,
    licença, direitos, resolução, tamanho, e só então o temático da cena.
    Devolver o MOTIVO (e não um booleano) é o que permite a folha de
    contato explicar por que a imagem não entrou.

    Aceita `MediaAsset` ou dict (`to_dict()`): o buscador tem o objeto, o
    relatório tem o dict, e os dois precisam da mesma resposta.
    """
    data = asset if isinstance(asset, dict) else asset.to_dict()
    url = str(data.get("download_url") or "")
    if not url:
        return "sem URL de download"
    if not is_image_url(url):
        return "não é imagem (jpg/png/webp)"
    license_text = str(data.get("license") or "")
    if not license_ok(license_text):
        return f"licença não permite edição: {license_text or 'desconhecida'}"
    if classify_rights(license_text, str(data.get("provider") or "")) == "blocked":
        return f"licença bloqueada: {license_text or 'desconhecida'}"
    floor = min_dimension()
    w, h = int(data.get("width") or 0), int(data.get("height") or 0)
    if w > 0 and h > 0 and min(w, h) < floor:
        return f"resolução {w}x{h} menor que {floor}px"
    size = int(data.get("size_bytes") or 0)
    ceiling = MAX_BYTES if max_bytes is None else int(max_bytes)
    if size and size > ceiling:
        return f"arquivo {size // 1024}KB acima do teto"
    return rejection_reason(data, blocked)
