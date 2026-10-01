"""Slugificação de ideias para nomes de diretório (PRD §15)."""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime


def slugify(text: str, max_len: int = 40) -> str:
    norm = unicodedata.normalize("NFKD", text.lower())
    ascii_only = "".join(c for c in norm if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or "video")[:max_len].strip("-") or "video"


def slugify_with_timestamp(text: str, max_len: int = 40) -> str:
    """Gera slug datado: YYYYMMDD_titulo (só a data, sem hora)."""
    stamp = datetime.now().strftime("%Y%m%d")
    base = slugify(text, max_len - 9)  # reserva espaço para data + "_"
    return f"{stamp}_{base}" or f"{stamp}_video"


def project_dir(out_dir: str, genre: str, slug: str) -> str:
    """Pasta do projeto: output/<genero>/<slug>, ou output/<slug> sem gênero.

    Com gênero escolhido, o vídeo sempre cai na pasta do gênero (uma
    pasta por gênero); sem gênero, mantém o layout plano legado.
    """
    genre = (genre or "").strip().lower()
    if genre:
        return os.path.join(out_dir, genre, slug)
    return os.path.join(out_dir, slug)


def find_project_root(out_dir: str, slug: str) -> str | None:
    """Localiza a pasta de um projeto pelo slug (novo e legado).

    Procura primeiro no layout plano (`output/<slug>`, projetos antigos)
    e depois em `output/<genero>/<slug>` (ordem alfabética de gênero).
    Devolve o caminho ou None.
    """
    flat = os.path.join(out_dir, slug)
    if os.path.isdir(flat):
        return flat
    try:
        entries = sorted(os.listdir(out_dir))
    except OSError:
        return None
    for entry in entries:
        cand = os.path.join(out_dir, entry, slug)
        if os.path.isdir(cand):
            return cand
    return None


def unique_slug(out_dir: str, genre: str, slug: str, idea: str = "") -> str:
    """Evita colisão de mesma data + mesmo título no mesmo dia.

    Se a pasta existe e é do mesmo `idea` (rerun/cache), reutiliza;
    se é de outra ideia, sufixa `-2`, `-3`… em vez de sobrescrever.
    """
    import json as _json
    root = project_dir(out_dir, genre, slug)
    if not os.path.isdir(root):
        return slug
    try:
        with open(os.path.join(root, "metadata.json"),
                   encoding="utf-8") as fh:
            same = (_json.load(fh).get("input", "") or "").strip() == idea.strip()
        if same:
            return slug
    except (OSError, ValueError):
        pass
    for n in range(2, 100):
        cand = f"{slug}-{n}"
        if not os.path.isdir(project_dir(out_dir, genre, cand)):
            return cand
    return slug
