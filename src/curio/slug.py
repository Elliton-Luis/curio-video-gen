"""Slugificação de ideias para nomes de diretório (PRD §15)."""

from __future__ import annotations

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
    """Gera slug com timestamp: YYYYMMDD-HHMMSS_titulo."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = slugify(text, max_len - 15)  # reserva espaço para timestamp + "_"
    return f"{timestamp}_{base}" or f"{timestamp}_video"
